import sys
import os
from pathlib import Path
import json
import logging
import datetime
from typing import Dict, Any, Optional

# 로깅 설정
logger = logging.getLogger("TradingAnalyzerSkill")

# 프로젝트 루트 및 tmp 경로 추가 (kis_v2, make_korea_db 임포트용)
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TMP_DIR = PROJECT_ROOT / "tmp"
if str(TMP_DIR) not in sys.path:
    sys.path.insert(0, str(TMP_DIR))

# 의존성 임포트
try:
    import kis_v2
    import make_korea_db
    import FinanceDataReader as fdr
    import pandas as pd
except ImportError as e:
    logger.error(f"필수 라이브러리 또는 모듈을 임포트할 수 없습니다: {e}")

import ollama
from shared.config_loader import NexusConfig

class TradingAnalyzerSkill:
    """
    한국 주식 분석 및 트레이딩 지원 스킬
    """
    name = "trading_analyzer"
    description = "한국 주식 시세 조회, 재무 요약, 차트 분석 및 데이터베이스 관리 스킬"
    version = "1.0.0"

    def search_stock_code(self, name: str) -> str:
        """종목명으로 티커 코드 검색"""
        return make_korea_db.get_code_name(name)

    def get_current_price(self, code: str) -> Dict[str, Any]:
        """현재가 및 52주 고저가 조회"""
        now = datetime.datetime.now()
        try:
            # 최근 10일치 데이터를 가져와서 마지막 종가 확인
            df = fdr.DataReader(code, (now - datetime.timedelta(days=10)).strftime('%Y%m%d'))
            if df.empty:
                return {"error": f"No data found for code {code}"}
            last = df.iloc[-1]
            
            # 52주 데이터
            df_year = fdr.DataReader(code, (now - datetime.timedelta(days=365)).strftime('%Y%m%d'))
            high_52 = df_year['High'].max()
            low_52 = df_year['Low'].min()
            
            res = {
                "code": code,
                "current_price": int(last['Close']),
                "change_percent": round((last['Close'] - df.iloc[-2]['Close']) / df.iloc[-2]['Close'] * 100, 2) if len(df) > 1 else 0,
                "high": int(last['High']),
                "low": int(last['Low']),
                "volume": int(last['Volume']),
                "high_52w": int(high_52),
                "low_52w": int(low_52)
            }
            return res
        except Exception as e:
            return {"error": str(e)}

    def analyze_stock(self, name_or_code: str) -> Dict[str, Any]:
        """연간 성과 분석 및 추세선 차트 생성"""
        try:
            result = kis_v2.single_annual(name_or_code)
            if result[0]:
                return {"status": "success", "result": result[1]}
            else:
                return {"status": "failed", "message": "데이터 부족 또는 추세를 찾을 수 없음"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_financial_summary(self, code: str) -> Dict[str, Any]:
        """재무 지표 요약 (PER, PBR, ROE 등)"""
        try:
            return make_korea_db.snapshot(code)
        except Exception as e:
            return {"error": str(e)}

    def get_business_headline(self, code: str) -> str:
        """기업 개요 헤드라인"""
        try:
            headline = kis_v2.get_stock_headline(code)
            return headline or "사업 요약 정보 없음"
        except Exception as e:
            return f"Error: {str(e)}"

    def refresh_stock_db(self, code: str) -> str:
        """로컬 데이터베이스 업데이트"""
        try:
            make_korea_db.save_year_data(code)
            make_korea_db.save_tooja_data(code)
            return f"Database updated successfully for {code}."
        except Exception as e:
            return f"Failed to update database for {code}: {str(e)}"

    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        메인 실행 로직. 자연어 쿼리를 분석하여 적절한 도구를 호출합니다.
        """
        query = params.get("query", "")
        action = params.get("action")
        target = params.get("target") # code or name

        if not action and query:
            # Ollama를 사용하여 의도 및 파라미터 추출
            action, target = self._parse_intent(query)
            logger.info(f"추출된 의도: action={action}, target={target}")

        if not action:
            return {"error": "실행할 액션을 결정할 수 없습니다. query 또는 action 파라미터가 필요합니다."}

        if not target and action != "list":
             return {"error": f"액션 '{action}'에 필요한 대상(종목명 또는 코드)이 없습니다."}

        # 액션별 분기
        if action == "price":
            # 종목명이면 코드로 변환 시도
            code = target if target.isdigit() else self.search_stock_code(target)
            if "not found" in code.lower(): return {"error": f"종목 '{target}'을 찾을 수 없습니다."}
            return self.get_current_price(code)
            
        elif action == "analyze":
            return self.analyze_stock(target)
            
        elif action == "summary":
            code = target if target.isdigit() else self.search_stock_code(target)
            if "not found" in code.lower(): return {"error": f"종목 '{target}'을 찾을 수 없습니다."}
            return self.get_financial_summary(code)
            
        elif action == "headline":
            code = target if target.isdigit() else self.search_stock_code(target)
            if "not found" in code.lower(): return {"error": f"종목 '{target}'을 찾을 수 없습니다."}
            return {"headline": self.get_business_headline(code)}
            
        elif action == "refresh":
            code = target if target.isdigit() else self.search_stock_code(target)
            if "not found" in code.lower(): return {"error": f"종목 '{target}'을 찾을 수 없습니다."}
            return {"message": self.refresh_stock_db(code)}
            
        elif action == "search":
            return {"code": self.search_stock_code(target)}

        return {"error": f"지원하지 않는 액션입니다: {action}"}

    def _parse_intent(self, query: str) -> tuple:
        """Ollama를 사용하여 자연어 쿼리에서 action과 target 추출"""
        model = NexusConfig.get_model("worker")
        prompt = f"""
        사용자 질문에서 한국 주식 분석을 위한 '액션'과 '대상(종목명 또는 코드)'을 추출해줘.
        
        질문: "{query}"
        
        가능한 액션:
        - price: 현재가, 시세, 가격 조회
        - analyze: 성과 분석, 차트, 추세 분석
        - summary: 재무 요약, PER/PBR, 지표 조회
        - headline: 기업 개요, 사업 내용, 뭐하는 회사인지
        - refresh: 데이터 업데이트, DB 갱신
        - search: 종목 코드 검색
        
        반드시 다음 JSON 형식으로만 응답해:
        {{"action": "price", "target": "삼성전자"}}
        """
        
        try:
            response = ollama.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}]
            )
            result_text = response.get("message", {}).get("content", "")
            if "{" in result_text and "}" in result_text:
                json_str = result_text[result_text.find("{"):result_text.rfind("}")+1]
                extracted = json.loads(json_str)
                return extracted.get("action"), extracted.get("target")
        except Exception as e:
            logger.warning(f"의도 분석 실패: {e}")
        
        return None, None

def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """워커 엔트리포인트"""
    skill = TradingAnalyzerSkill()
    return skill.run(params)

if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.INFO)
    print(run({"query": "삼성전자 주가 알려줘"}))
    print(run({"query": "현대차 재무 요약해줘"}))
