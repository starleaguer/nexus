"""
S&P 500 섹터 수급 분석 및 성능/에러 내역 반환 스킬.
[사용 시점] 미국 시장의 전반적인 섹터별 흐름이나 수급 상태를 파악해야 할 때 사용.
[출력] 섹터별 거래대금 순위 및 수집 과정의 진단 데이터(성공/실패 내역).
"""

from typing import Dict, Any, List, Optional, Union
import json
import logging
import traceback
import time
from datetime import datetime
import yfinance as yf
import requests

# 로깅 설정: Nexus 시스템 표준 포맷 준수
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - [TraceID: %(process)d] - %(message)s'
)
logger = logging.getLogger("MarketFlowSkill")

# --- Advanced Custom Exceptions for Deep Error Analysis ---

class MarketFlowSkillError(Exception):
    """Base exception for MarketFlowSkill"""
    def __init__(self, message: str, error_type: str, context: Optional[Dict] = None):
        super().__init__(message)
        self.error_type = error_type
        self.cap_context = context or {}

class MarketFlowValidationError(MarketFlowSkillError):
    """Gatekeeper 단계에서 발생하는 데이터 유효성 검사 에러"""
    def __init__(self, message: str, context: Optional[Dict] = None):
        super().__init__(message, "ValidationError", context)

class MarketFlowDataFetchError(MarketFlowSkillError):
    """데이터 수집 관련 상위 에러"""
    def __init__(self, message: str, error_subtype: str, context: Optional[Dict] = None):
        super().__init__(message, f"DataFetchError.{error_subtype}", context)

class MarketFlowNetworkError(MarketFlowDataFetchError):
    """네트워크 타임아웃 또는 연결 실패 (Retry 가능성이 높은 에러)"""
    def __init__(self, message: str, context: Optional[Dict] = None):
        super().__init__(message, "NetworkError", context)

class MarketFlowParsingError(MarketFlowDataFetchError):
    """데이터 포맷 불일치 또는 파싱 실패 (데이터 무결성 에러)"""
    def __init__(self, message: str, context: Optional[Dict] = None):
        super().__init__(message, "ParsingError", context)

# S&P 500 주요 11개 섹터 ETF 목록
SECTOR_ETFS = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB"
}

class MarketFlowSkill:
    """시장 흐름 분석 스킬 (Nexus Workflow Engine 최적화 버전)"""
    
    name = "market_flow"
    description = "S&P 500 섹터별 수급(거래대금) 분석 및 에러 진단"
    version = "1.4.0"
    
    def __init__(self):
        self.timeout = 10  # 10초 타임아웃 설정
        
    def _gatekeeper(self, data: Dict[str, Any]) -> None:
        """파라미터 유효성 검사"""
        if not isinstance(data, dict):
            raise MarketFlowValidationError(
                f"Input must be dict, got {type(data).__name__}",
                context={"input_type": type(data).__name__}
            )
        
        if "query" not in data:
            raise MarketFlowValidationError("Missing required parameter: 'query'")
            
        if not isinstance(data["query"], str) or not data["query"].strip():
            raise MarketFlowValidationError(
                "The 'query' parameter must be a non-empty string",
                context={"query_value": data.get("query")}
            )

    def _fetch_single_sector(self, sector_name: str, ticker_symbol: str) -> Dict[str, Any]:
        """
        개별 티커 데이터를 가져오는 격리된 메서드.
        성공 시 데이터, 실패 시 상세 에러 컨텍스트를 반환하여 분석을 지원함.
        """
        start_time = time.perf_counter()
        try:
            ticker = yf.Ticker(ticker_symbol)
            # yfinance 내부적으로 발생하는 네트워크 지연을 모니터링하기 위해 period 설정
            hist = ticker.history(period="1d")
            
            latency = time.perf_counter() - start_time
            
            if hist.empty:
                return {
                    "status": "failed",
                    "sector": sector_name,
                    "ticker": ticker_symbol,
                    "error_type": "EmptyDataError",
                    "message": "No historical data available for this period.",
                    "latency": latency
                }
                
            close_price = hist['Close'].iloc[0]
            volume = hist['Volume'].iloc[0]
            trading_value = float(close_price * volume)
            
            return {
                "status": "success",
                "sector": sector_name,
                "ticker": ticker_symbol,
                "trading_value": trading_value,
                "close_price": float(close_price),
                "volume": int(volume),
                "latency": latency
            }

        except requests.exceptions.Timeout:
            return {
                "status": "failed",
                "sector": sector_name,
                "ticker": ticker_symbol,
                "error_type": "NetworkTimeoutError",
                "message": "API request timed out.",
                "latency": time.perf_counter() - start_time
            }
        except Exception as e:
            return {
                "status": "failed",
                "sector": sector_name,
                "ticker": ticker_symbol,
                "error_type": type(e).__name__,
                "message": str(e),
                "latency": time.perf_counter() - start_time
            }

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """시장 분석 수행 및 결과 리포팅"""
        result = {
            "skill": self.name,
            "version": self.version,
            "timestamp": datetime.now().isoformat(),
            "status": "success",
            "analysis": None,
            "error": None,
            "error_context": None,
            "diagnostics": {
                "success_count": 0,
                "failure_count": 0,
                "failure_details": []
            }
        }

        try:
            # 1. Gatekeeper execution
            self._gatekeeper(data)
            
            sector_results = []
            
            # 2. Data Collection Loop
            for sector_name, ticker_symbol in SECTOR_ETFS.items():
                sector_res = self._fetch_single_sector(sector_name, ticker_symbol)
                
                if sector_reg := sector_res.get("status") == "success":
                    sector_results.append(sector_res)
                    result["diagnostics"]["success_count"] += 1
                else:
                    # 실패 시 상세 내용을 diagnostics에 기록 (Error Analysis 지원)
                    result["diagnostics"]["failure_count"] += 1
                    result["diagnostics"]["failure_details"].append({
                        "sector": sector_res["sector"],
                        "ticker": sector_res["ticker"],
                        "error_type": sector_res["error_type"],
                        "message": sector_res["message"],
                        "latency": sector_res["latency"]
                    })
            
            # 3. Result Aggregation & Final Status Determination
            if not sector_results:
                result["status"] = "error"
                result["error"] = {
                    "type": "CriticalDataFetchError", 
                    "message": "All sector data collection failed."
                }
            else:
                # 거래대금 기준 정렬
                sector_results.sort(key=lambda x: x["trading_value"], reverse=True)
                
                result["analysis"] = {
                    "top_sectors": sector_results,
                    "summary": f"Analyzed {len(sector_results)} sectors. "
                               f"Top sector: {sector_results[0]['sector']}."
                }
                
                if result["diagnostics"]["failure_count"] > 0:
                    result["status"] = "partial_success"

        except MarketFlowValidationError as ve:
            logger.error(f"Validation Error: {str(ve)}")
            result["status"] = "error"
            result["error"] = {"type": ve.error_type, "message": str(ve)}
            result["error_context"] = ve.cap_context
            
        except Exception as e:
            error_trace = traceback.format_exc()
            logger.critical(f"Unexpected Execution Error: {str(e)}\n{error_trace}")
            result["status"] = "error"
            result["error"] = {
                "type": "RuntimeError", 
                "message": "An internal error occurred during analysis."
            }
            result["error_context"] = {
                "exception_type": type(e).__name__,
                "detail": str(e),
                "traceback": error_trace.splitlines()[-3:] # 마지막 3줄만 요약 제공
            }
            
        return result


def run(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """S&P 500 섹터 수급 및 시장 흐름 분석 도구.
    [사용 시점] 
    - 미국 시장 전체의 섹터별 자금 유입/유출 및 흐름을 파악하고 싶을 때
    - 개별 종목이 아닌, 기술주/에너지주 등 '섹터 단위'의 성과가 궁금할 때
    
    [파라미터]
    - query: 분석 요청 문구 (필수, 예: "현재 미국 시장 섹터별 흐름 분석해줘")
    
    [출력] 
    섹터별 거래대금 순위 및 성과 분석 데이터 반환
    """
    try:
        skill = MarketFlowSkill()
        return skill.analyze(input_data)
    except Exception as e:
        logger.critical(f"Critical Worker Failure: {str(e)}", exc_info=True)
        return {
            "skill": "market_flow",
            "status": "error",
            "error": {
                "type": "CriticalSystemError", 
                "message": "The worker process encountered a fatal error."
            },
            "error_context": {"exception": str(e)}
        }

if __name__ == "__main__":
    # 테스트 케이스 실행
    print("\n[Test 1] Valid Input - Full Analysis")
    print(json.dumps(run({"query": "Analyze market flow"}), indent=2, ensure_ascii=False))

    print("\n[Test 2] Validation Error - Missing Query")
    print(json.dumps(run({"not_query": "test"}), indent=2, ensure_ascii=False))

    print("\n[Test 3] Validation Error - Wrong Type")
    print(json.dumps(run(["not", "a", "dict"]), indent=2, ensure_ascii=False))