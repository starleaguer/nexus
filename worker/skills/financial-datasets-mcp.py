import logging
from typing import Dict, Any
import sys
from pathlib import Path

# Add project root and the mcp package to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    
MCP_ROOT = PROJECT_ROOT / "temp_tools" / "financial-datasets-mcp"
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))

logger = logging.getLogger(__name__)

def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Financial Datasets MCP Wrapper
    """
    query = params.get("query", "")
    
    # 이 부분에 FastMCP 서버 또는 내부 Python API를 호출하는 로직을 추가하세요.
    # 예: get_income_statements(ticker="AAPL")
    
    logger.info(f"Financial Datasets MCP 호출됨 (query: {query})")
    
    return {
        "status": "success",
        "message": "Financial Datasets MCP가 정상적으로 호출되었습니다. (상세 로직 구현 필요)",
        "query": query
    }
