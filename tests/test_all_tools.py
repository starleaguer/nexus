import asyncio
import json
import logging
import argparse
import importlib
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가 (tests/ 폴더 내에 있으므로 parent.parent)
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config_loader import NexusConfig
from core.orchestrator import Orchestrator
from core.model_selector import ModelAvailabilityService
from shared.utils import extract_json_from_text

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ToolTester")

# 도구별 기본 테스트 파라미터 맵핑 (AI 생성 실패 시 폴백용)
DEFAULT_PARAMS = {
    "trading_analyzer": {"action": "price", "target": "삼성전자"},
    "market_flow": {"query": "S&P 500 시장 수급 분석"},
    "web_researcher": {"query": "오늘 대한민국 코스피 지수는 어때?"},
}

async def generate_test_params(orchestrator, tool_name, description, task_type="medium", tier=None):
    """AI를 사용하여 도구 설명에 맞는 테스트 파라미터 생성"""
    system_prompt = f"""너는 Nexus 시스템의 QA 엔지니어다. 
다음 도구의 이름과 설명을 보고, 이 도구가 정상적으로 작동하는지 테스트하기 위한 최적의 JSON 파라미터를 생성해줘.
모든 도구는 'query' 파라미터를 필수로 요구할 수 있으니 적절한 검색어(query)를 반드시 포함해줘.
오직 JSON 객체만 출력하고 다른 설명은 하지 마.

[도구 이름]: {tool_name}
[도구 설명]: {description}
"""
    user_prompt = "이 도구를 테스트하기 위한 JSON 파라미터를 생성해줘."
    
    try:
        # 지정된 task_type(티어 포함)에 따라 최적 모델 선택
        svc = ModelAvailabilityService()
        model_info = await svc.get_best_available_model(task=task_type, tier=tier)
        
        logger.info(f"🤖 [Param Gen] Using {model_info['provider']} ({model_info['model']}) for {tool_name}")
        
        response = await orchestrator.llm.chat(
            system_prompt, 
            user_prompt, 
            use_remote=(model_info['provider'] == 'worker'),
            model=model_info['model'],
            step="Test Param Generation"
        )
        
        parsed = extract_json_from_text(response)
        if parsed:
            # 필수 필드(query) 누락 시 방어적 주입 (Skill validation 통과용)
            if "query" not in parsed:
                parsed["query"] = description or tool_name
            return parsed

    except Exception as e:
        logger.warning(f"AI 파라미터 생성 실패 ({tool_name}): {e}")
    
    return DEFAULT_PARAMS.get(tool_name, {"query": "test"})

async def test_tool(tool_name, params):
    print(f"\n[🚀 Testing Tool]: {tool_name}")
    print(f"   - Generated Params: {params}")
    
    try:
        # 1. 동적 로딩 시도 (skills 폴더 내)
        module = importlib.import_module(f"skills.{tool_name}")
        if hasattr(module, "run"):
            # 비동기 함수인 경우 처리
            if asyncio.iscoroutinefunction(module.run):
                result = await module.run(params)
            else:
                result = module.run(params)
            
            print(f"   ✅ SUCCESS: {tool_name} executed successfully.")
            print(f"   - Result Snippet: {str(result)[:200]}...")
            return True
    except ImportError:
        print(f"   ℹ️ Inform: {tool_name} is likely an MCP tool or specialized skill.")
    except Exception as e:
        print(f"   ❌ FAILED: {tool_name} execution error: {e}")
        return False
    
    return False

async def main():
    parser = argparse.ArgumentParser(description="Nexus Tool Connectivity Tester")
    parser.add_argument("--tool", type=str, help="테스트할 특정 도구 이름")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3], default=2, help="파라미터 생성에 사용할 LLM 티어 (1:Cloud, 2:Worker, 3:Local)")
    args = parser.parse_args()

    print("=" * 60)
    print("Nexus Distributed System - AI-Driven Tools Connectivity Test")
    print("=" * 60)

    # 오케스트레이터 및 서비스 초기화 (재사용)
    orchestrator = Orchestrator()
    
    # 티어에 따른 task_type 설정
    tier_map = {1: "fast", 2: "medium", 3: "deep"}
    task_type = tier_map.get(args.tier, "medium")

    # 1. 탐색된 스킬 목록 가져오기
    skills = NexusConfig.get_discovered_skills()
    mcp_tools = NexusConfig.load_manifest().get("tools", {}).get("mcp", [])
    
    all_tools = []
    for s in skills:
        all_tools.append({"name": s['name'], "description": s.get('description', '')})
    for m in mcp_tools:
        all_tools.append({"name": m.get('name'), "description": m.get('description', '')})

    # 특정 도구만 필터링
    if args.tool:
        all_tools = [t for t in all_tools if t['name'] == args.tool]
        if not all_tools:
            print(f"❌ Error: 도구 '{args.tool}'를 찾을 수 없습니다.")
            return

    print(f"\n[Total Tools to Test: {len(all_tools)}]")
    print(f"[Selected Tier: {args.tier} ({task_type})]")

    # 2. 개별 테스트 수행
    success_count = 0
    for tool_info in all_tools:
        tool_name = tool_info["name"]
        description = tool_info["description"]
        
        # AI를 통해 도구 설명에 맞는 파라미터 동적 생성
        params = await generate_test_params(orchestrator, tool_name, description, task_type=task_type, tier=args.tier)
        
        if await test_tool(tool_name, params):
            success_count += 1
        await asyncio.sleep(0.5)

    print("\n" + "=" * 60)
    print(f"Test Finished: {success_count}/{len(all_tools)} tools tested.")
    print("=" * 60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
