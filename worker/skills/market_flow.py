"""
Market Flow 분석 스킬 - yfinance를 활용한 S&P 500 섹터 수급 분석
"""
from typing import Dict, Any, List
import json
from datetime import datetime
import yfinance as yf

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
    """시장 흐름 분석 스킬"""
    
    name = "market_flow"
    description = "S&P 500 섹터별 수급(거래대금) 분석"
    
    def __init__(self):
        self.version = "1.1.0"
    
    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        시장 분석 수행
        
        Args:
            data: 분석 파라미터 (LLM이 넘겨준 값들)
        
        Returns:
            분석 결과
        """
        result = {
            "skill": self.name,
            "timestamp": datetime.now().isoformat(),
            "analysis": {
                "top_sectors": []
            }
        }
        
        sector_volumes = []
        
        # 각 섹터 ETF의 오늘 거래대금(대략적으로 가장 최근일 거래량 * 종가) 계산
        for sector_name, ticker_symbol in SECTOR_ETFS.items():
            try:
                ticker = yf.Ticker(ticker_symbol)
                # 최근 1일치 데이터 조회
                hist = ticker.history(period="1d")
                if not hist.empty:
                    close_price = hist['Close'].iloc[0]
                    volume = hist['Volume'].iloc[0]
                    trading_value = close_price * volume
                    
                    sector_volumes.append({
                        "sector": sector_name,
                        "ticker": ticker_symbol,
                        "trading_value": float(trading_value),
                        "close_price": float(close_price),
                        "volume": int(volume)
                    })
            except Exception as e:
                # 에러 발생 시 로깅 또는 무시
                pass
                
        # 거래대금 편의상 높은 순으로 정렬
        sector_volumes.sort(key=lambda x: x["trading_value"], reverse=True)
        
        result["analysis"]["top_sectors"] = sector_volumes
        result["analysis"]["summary"] = f"가장 거래대금이 높은 섹터는 {sector_volumes[0]['sector']} ({sector_volumes[0]['ticker']}) 입니다." if sector_volumes else "데이터가 없습니다."
        
        return result


# 스킬 실행 엔트리포인트
def run(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """스킬 실행"""
    skill = MarketFlowSkill()
    return skill.analyze(input_data)

if __name__ == "__main__":
    # 테스트
    test_data = {"query": "현재 거래대금 상위 섹터가 뭐야?"}
    result = run(test_data)
    print(json.dumps(result, indent=2))