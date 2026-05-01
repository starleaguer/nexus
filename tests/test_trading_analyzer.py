import asyncio
import json
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가 (tests/ 폴더 내에 있으므로 parent.parent)
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from skills.trading_analyzer import run as trading_analyzer_run
from core.orchestrator import Orchestrator

# 테스트 전용 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def run_test():
    print("=" * 60)
    print("🚀 Trading Analyzer Skill Comprehensive Test")
    print("=" * 60)

    test_stock = "현대차"
    
    # 1. 개별 액션 테스트
    actions = ["price", "analyze", "summary", "headline", "refresh"]
    
    print(f"\n📊 1. 개별 액션 테스트 (대상: {test_stock})")
    for action in actions:
        print(f"\n[Action: {action}]")
        params = {"action": action, "target": test_stock}
        try:
            result = trading_analyzer_run(params)
            if result.get("status") == "success":
                print(f"✅ 성공: {action}")
                # 결과 샘플 출력 (너무 길면 자름)
                output = json.dumps(result, ensure_ascii=False, indent=2)
                print(f"   결과: {output[:300]}..." if len(output) > 300 else f"   결과: {output}")
            else:
                print(f"❌ 실패: {action} - {result.get('message')}")
        except Exception as e:
            print(f"💥 에러 발생 ({action}): {e}")

    # 2. 자연어 의도 분석 테스트
    print("\n🤖 2. 자연어 의도 분석 테스트")
    nlp_queries = [
        "하이닉스 지금 얼마야?",
        "현대차 재무 지표 좀 보여줘",
        "카카오 주가 차트 분석해줘",
        "네이버 어떤 회사야?"
    ]
    
    for query in nlp_queries:
        print(f"\n[Query: '{query}']")
        try:
            result = trading_analyzer_run({"query": query})
            if result.get("status") == "success":
                print(f"✅ 분석 성공")
                output = json.dumps(result, ensure_ascii=False, indent=2)
                print(f"   결과: {output[:200]}...")
            else:
                print(f"❌ 분석 실패: {result.get('message')}")
        except Exception as e:
            print(f"💥 에러 발생: {e}")

    # 3. 존재하지 않는 종목 테스트 (에러 핸들링)
    print("\n⚠️ 3. 존재하지 않는 종목 테스트")
    invalid_params = {"action": "price", "target": "존재하지않는회사123"}
    try:
        result = trading_analyzer_run(invalid_params)
        print(f"   결과 (예상된 실패): {result.get('status')} - {result.get('message')}")
    except Exception as e:
        print(f"   결과 (에러): {e}")

    # 4. 오케스트레이터 통합 테스트
    print("\n🌐 4. 오케스트레이터 통합 테스트")
    orchestrator = Orchestrator()
    complex_query = "LG에너지솔루션 주가 분석하고 재무 상태 알려줘"
    print(f"   질문: '{complex_query}'")
    
    try:
        # 오케스트레이터는 도구를 자율적으로 선택함
        response = await orchestrator.run(complex_query)
        print("✅ 오케스트레이터 응답 완료")
        
        # 도구가 실행되었는지 확인
        if response.get("worker_result"):
            print("   - 도구 실행 확인됨")
            print(f"   - AI 요약 리포트 일부: {response.get('final_report', '')[:300]}...")
        else:
            print("   ⚠️ 도구가 실행되지 않았거나 직접 응답함")
            
    except Exception as e:
        print(f"❌ 오케스트레이터 테스트 실패: {e}")

    print("\n" + "=" * 60)
    print("✅ 모든 테스트 완료")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_test())
