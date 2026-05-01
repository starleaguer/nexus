import sys
import json
import uuid
import logging
from pprint import pprint

from pathlib import Path
# 프로젝트 루트를 path에 추가 (tests/ 폴더 내에 있으므로 parent.parent)
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.memory_manager import MemoryManager

logging.basicConfig(level=logging.WARNING)

def test_memory_manager():
    print("=" * 60)
    print("🧠 [테스트] MemoryManager 기능 확인")
    print("=" * 60)

    try:
        mm = MemoryManager()
        print("✅ MemoryManager 인스턴스화 성공")
    except Exception as e:
        print(f"❌ MemoryManager 인스턴스화 실패: {e}")
        return

    # 1. SQLite Task Log 저장 테스트
    print("\n▶ 1. SQLite 작업 로그(Task Log) 테스트")
    try:
        task_id = str(uuid.uuid4())
        save_success = mm.save_log(task_id, "test_task", "completed", {"test": "data"}, {"result": "success"})
        if save_success:
            log_data = mm.get_task_log(task_id)
            if log_data and log_data.get('task_id') == task_id:
                print("   ✅ 성공: 로그 저장 및 조회 완벽 작동")
            else:
                print("   ❌ 실패: 저장된 로그를 찾을 수 없거나 데이터 불일치")
        else:
            print("   ❌ 실패: 로그 저장 오류")
    except Exception as e:
        print(f"   ❌ 에러: {e}")

    # 2. ChromaDB Principles (RAG) 테스트
    print("\n▶ 2. ChromaDB 투자 원칙(Principles) 테스트")
    try:
        if mm.principles_collection is None:
            print("   ⚠️ 주의: ChromaDB 컬렉션이 초기화되지 않음 (chromadb 모듈 미설치 등)")
        else:
            # 저장
            principle_id = str(uuid.uuid4())
            p_save = mm.save_principle(principle_id=principle_id, content="항상 손절매는 5%에서 기계적으로 한다.", category="risk_management")
            
            if p_save:
                # 검색
                results = mm.get_relevant_principles("손절매 기준이 뭐야?", n_results=1)
                if results and "손절매" in results[0]['content']:
                    print("   ✅ 성공: ChromaDB 투자 원칙 저장 및 RAG 검색 완벽 작동")
                else:
                    print(f"   ❌ 실패: 저장 후 검색 결과 불일치: {results}")
            else:
                print("   ❌ 실패: 투자 원칙 저장 오류")
    except Exception as e:
        print(f"   ❌ 에러: {e}")

    # 3. ChromaDB User Profile 테스트
    print("\n▶ 3. ChromaDB 사용자 성향(User Profile) 테스트")
    try:
        if mm.user_profile_collection:
            u_save = mm.save_user_profile("user1", "공격적인 기술주 투자 성향을 가짐")
            if u_save:
                profile = mm.get_user_profile("user1")
                if profile and "공격적인" in profile.get('profile', ''):
                    print("   ✅ 성공: 사용자 성향 저장 및 조회 완벽 작동")
                else:
                    print(f"   ❌ 실패: 사용자 성향 조회 불일치: {profile}")
            else:
                print("   ❌ 실패: 사용자 성향 저장 오류")
    except Exception as e:
        print(f"   ❌ 에러: {e}")

    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)

if __name__ == "__main__":
    test_memory_manager()
