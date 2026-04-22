import asyncio
import os
import logging
from manager.manager_core import ManagerCore
from shared.config_loader import NexusConfig

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("LocalTest")

async def run_local_test():
    """
    워커 서버 없이 로컬에서 전체 워크플로우를 테스트합니다.
    """
    print("=" * 60)
    print("Nexus 로컬 테스트 모드 시작")
    print("=" * 60)
    
    # 1. 매니저 초기화 (Local Mode 활성화)
    try:
        manager = ManagerCore(local_mode=True)
        print("✓ ManagerCore 로컬 모드 준비 완료")
    except Exception as e:
        print(f"❌ 초기화 실패: {e}")
        return

    # 2. 테스트 질문
    # user_input = "삼성전자 현재 주가랑 재무 요약 좀 해줘"
    user_input = "현재 시장 섹터별 흐름 분석해줘"
    
    print(f"\n[질문]: {user_input}")
    print("-" * 60)
    
    try:
        # 3. 워크플로우 실행
        result = await manager.run(user_input=user_input, user_id="test_user")
        
        # 4. 결과 출력
        print("\n" + "=" * 60)
        print("최종 리포트")
        print("=" * 60)
        
        if result.get("error"):
            print(f"❌ 오류 발생: {result['error']}")
        else:
            print(result.get("final_report", "리포트 생성 실패"))
            
            # 연구 히스토리 요약 출력
            print("\n" + "-" * 60)
            print("연구 히스토리:")
            # ManagerCore의 state에 접근하기 어렵다면 result에서 가져옴
            if result.get("worker_summary"):
                print(f"마지막 작업 요약: {result['worker_summary']}")
                
    except Exception as e:
        print(f"❌ 실행 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_local_test())
