import logging
from typing import Dict, Any
import sys
from pathlib import Path

# Add project root and the mcp package to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    
MCP_ROOT = PROJECT_ROOT / "temp_tools" / "kospi-kosdaq-stock-server"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

logger = logging.getLogger(__name__)

def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    KOSPI/KOSDAQ Stock Server Wrapper
    """
    query = params.get("query", "")
    logger.info(f"KOSPI/KOSDAQ Stock Server 호출됨 (query: {query})")
    
    return {
        "status": "success",
        "message": "국내 주식 데이터 서버가 정상적으로 로드되었습니다. (상세 로직 구현 필요)",
        "query": query
    }
