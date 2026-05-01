"""MCP 서버 통신 브릿지. [파라미터] target_mcp: 실행할 MCP 서버 이름"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class MCPBridge:
    """
    여러 MCP 서버(예: Chrome, Reddit, TradingView 등)를 통합 호출하는 브릿지 인터페이스.
    Nexus의 메인 오케스트레이터와 개별 MCP 서버 간의 통신을 중계합니다.
    """
    def __init__(self):
        # 향후 각 MCP 클라이언트 세션이나 파이프를 관리하는 로직이 들어갑니다.
        pass
        
    def execute(self, mcp_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        지정된 MCP 서버로 명령을 라우팅하고 결과를 반환합니다.
        """
        logger.info(f"🌉 [MCP Bridge] 라우팅 요청: '{mcp_name}' 서버로 전달 중...")
        
        # 모델 정보에 따른 Context Window 동적 할당 로직을 MCP 서버로도 전파
        model_info = params.get("current_model_info", {})
        
        try:
            # 동적 임포트를 통한 서브 폴더 내 스킬 실행 (예: skills/tradingview_mcp/main.py)
            import importlib
            module = importlib.import_module(f"skills.{mcp_name}.main")
            
            if hasattr(module, "run"):
                return module.run(params)
            else:
                return {"error": f"MCP '{mcp_name}' 모듈에 실행 가능한 run() 메서드가 없습니다."}
        except ImportError:
            return {"error": f"MCP '{mcp_name}' 모듈을 찾을 수 없거나 연결 실패했습니다."}
        except Exception as e:
            logger.error(f"MCP Bridge Error [{mcp_name}]: {e}")
            return {"error": str(e)}

def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """Nexus 시스템에서 단일 진입점(Entry Point)으로 활용"""
    bridge = MCPBridge()
    mcp_name = params.get("target_mcp")
    
    if not mcp_name:
        return {"error": "호출할 대상 MCP 이름(target_mcp)이 파라미터에 없습니다."}
        
    return bridge.execute(mcp_name, params)
