import json
import logging
from typing import Dict, Any

import ollama
from tradingview_mcp.server import combined_analysis

# shared_config 로드 
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    
from shared.config_loader import NexusConfig

logger = logging.getLogger(__name__)

def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    tradingview-mcp 래퍼 함수
    자연어 쿼리에서 심볼과 거래소를 추출하고 combined_analysis를 실행합니다.
    """
    query = params.get("query", "")
    if not query:
        return {"error": "Query parameter is required"}

    # 1. 쿼리에서 심볼과 거래소 추출 (Ollama 활용)
    model = NexusConfig.get_model("worker")
    prompt = f"""
    다음 사용자 질문에서 분석하려는 주식/암호화폐의 종목 티커(Symbol)와 거래소(Exchange)를 추출해줘.
    
    질문: "{query}"
    
    가이드라인:
    - 티커는 영문 대문자 (예: AAPL, TSLA, BTCUSDT)
    - 거래소는 NASDAQ, NYSE, BINANCE, KUCOIN, BIST, EGX 등 (모르면 NASDAQ 또는 BINANCE로 추정)
    
    반드시 다음 JSON 형식으로만 응답해:
    {{"symbol": "AAPL", "exchange": "NASDAQ"}}
    """
    
    symbol = "BTCUSDT"
    exchange = "BINANCE"
    
    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}]
        )
        result_text = response.get("message", {}).get("content", "")
        
        # JSON 추출
        if "{" in result_text and "}" in result_text:
            json_str = result_text[result_text.find("{"):result_text.rfind("}")+1]
            extracted = json.loads(json_str)
            symbol = extracted.get("symbol", symbol)
            exchange = extracted.get("exchange", exchange)
            logger.info(f"추출된 정보: symbol={symbol}, exchange={exchange}")
    except Exception as e:
        logger.warning(f"심볼 추출 실패, 기본값 사용: {e}")
        
    # 2. tradingview-mcp의 combined_analysis 실행
    logger.info(f"tradingview-mcp 실행 중: {symbol} on {exchange}")
    try:
        analysis_result = combined_analysis(symbol=symbol, exchange=exchange, timeframe="1D")
        return analysis_result
    except Exception as e:
        logger.error(f"tradingview-mcp 실행 중 오류 발생: {e}")
        return {"error": str(e), "symbol": symbol, "exchange": exchange}
