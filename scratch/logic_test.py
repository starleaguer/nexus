import asyncio
import os
import sys
from pathlib import Path

# 프로젝트 루트를 경로에 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

async def test_hardware_routing():
    print("\n" + "="*50)
    print("🧪 Nexus Hardware-Aware Routing Test")
    print("="*50)
    
    from core.model_selector import ModelAvailabilityService
    selector = ModelAvailabilityService()
    
    # 1. 상황 설정: API는 모두 꺼져 있고, 로컬과 워커만 가용한 상태
    selector.status_cache = {
        "local": True,
        "worker": True,
        "gemini": False,
        "groq": False
    }
    
    # 지연 시간 설정 (로컬은 5ms로 매우 빠름, 워커는 네트워크 때문에 150ms로 느림)
    selector.latency_cache["local"] = 5.0
    selector.latency_cache["worker"] = 150.0
    
    # 상태 업데이트 함수 목(Mock) 처리
    async def mock_update(): pass
    selector.update_status = mock_update
    
    # 2. 모델 선택 실행
    # 같은 gemma2:9b 급 모델이 양쪽에 있다고 가정했을 때, 
    # RTX 보너스 vs 네트워크 지연 페널티가 어떻게 작용하는지 확인
    print("\n[Scenario: Local(5ms) vs RTX-Worker(150ms)]")
    best_model = await selector.get_best_available_model(task_complexity="medium")
    
    print(f"\n✅ Result: {best_model['model']} ({best_model['provider']})")
    print("="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(test_hardware_routing())
