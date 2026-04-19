import json
import logging
import asyncio
import threading
from typing import Dict, Any

import ollama

# shared_config 및 MarketRouter 임포트 
import sys
from pathlib import Path

# Add project root and temp_tools/borsa-mcp to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    
BORSA_MCP_ROOT = PROJECT_ROOT / "temp_tools" / "borsa-mcp"
if str(BORSA_MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(BORSA_MCP_ROOT))

from providers.market_router import MarketRouter
from models.unified_base import MarketType
from shared.config_loader import NexusConfig

logger = logging.getLogger(__name__)

def run_async_coroutine(coro):
    """지정된 비동기 함수를 새로운 이벤트 루프/스레드에서 실행합니다."""
    result = []
    error = []
    def runner():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            res = loop.run_until_complete(coro)
            result.append(res)
            loop.close()
        except Exception as e:
            error.append(e)
            
    t = threading.Thread(target=runner)
    t.start()
    t.join()
    if error:
        raise error[0]
    return result[0]

def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Borsa MCP 래퍼 함수
    자연어 쿼리에서 심볼/의도를 추출하고 MarketRouter를 통해 실행합니다.
    """
    query = params.get("query", "")
    if not query:
        return {"error": "Query parameter is required"}

    # 1. 자연어에서 의도 추출 (어떤 도구를 호출할지, 종목은 무엇인지)
    model = NexusConfig.get_model("worker")
    prompt = f"""
    다음 사용자 질문에서 검색하려는 주식 종목 티커(Symbol), 시장 종류(Market), 원하는 분석 정보(Intent)를 추출해줘.
    
    질문: "{query}"
    
    가이드라인:
    - Symbol: 영문 티커 (예: AAPL, GARAN, THYAO). 종목을 알 수 없다면 빈 문자열.
    - Market: bist, us, crypto_tr, crypto_global 중 하나 (예를 들어 애플,테슬라는 us, BIST이나 터키관련 종목은 bist, 그외는 us)
    - Intent: quick_info (기본/현재가/요약), profile (기업 정보/설명), technical (기술적 지표/차트), historical (과거 가격 데이터) 중 하나

    반드시 다음 JSON 형식으로만 응답해:
    {{"symbol": "AAPL", "market": "us", "intent": "quick_info"}}
    """
    
    symbol = "BTCUSDT"
    market_str = "crypto_global"
    intent = "quick_info"
    
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
            market_str = extracted.get("market", market_str)
            intent = extracted.get("intent", intent)
            logger.info(f"추출된 정보: symbol={symbol}, market={market_str}, intent={intent}")
    except Exception as e:
        logger.warning(f"의도 추출 실패, 기본값 사용: {e}")
        
    # Enum 매핑
    market_enum = MarketType.US
    for m in MarketType:
        if m.value == market_str:
            market_enum = m
            break
            
    # 2. Borsa MCP MarketRouter를 활용하여 정보 획득
    async def _execute():
        router = MarketRouter()
        if intent == "profile":
            return await router.get_profile(symbol, market_enum)
        elif intent == "technical":
            return await router.get_technical_analysis(symbol, market_enum, "1d")
        elif intent == "historical":
            return await router.get_historical_data(symbol, market_enum)
        else:
            return await router.get_quick_info(symbol, market_enum)

    logger.info(f"Borsa MCP 실행 중: {symbol} on {market_str} (intent: {intent})")
    try:
        return run_async_coroutine(_execute())
    except Exception as e:
        logger.error(f"Borsa MCP 실행 중 오류 발생: {e}")
        return {"error": str(e), "symbol": symbol, "market": market_str}
