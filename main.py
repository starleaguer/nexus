"""
Nexus Main - 분산 AI 작업 관리 시스템 진입점
방어적 코딩 적용: 네트워크 병목, 서버 다운 등 예외 상황 처리
"""
import asyncio
import os
import json
import sys
from pathlib import Path
from typing import Optional
import logging
from shared.config_loader import NexusConfig

# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).parent

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ==================== 설정 ====================
class Config:
    """설정 관리"""
    MAX_RETRIES = 3           # 최대 재시도 횟수
    RETRY_DELAY = 2           # 재시도 간격 (초)
    WORKER_TIMEOUT = NexusConfig.get_timeout("worker", 60)
    OLLAMA_TIMEOUT = NexusConfig.get_timeout("ollama", 60)
    
    # 설정 로더 사용
    DEFAULT_IP = "127.0.0.1"  # config_loader에서 처리됨
    DEFAULT_PORT = 8000
    MANIFEST_PATH = NexusConfig.MANIFEST_PATH


def load_manifest() -> dict:
    """매니페스트 로드 (중앙 로더 사용)"""
    return NexusConfig.load_manifest()


def get_worker_url() -> str:
    """RTX Worker URL 가져오기 (중앙 로더 사용)"""
    url = NexusConfig.get_worker_url()
    logger.info(f"Worker URL 확인: {url}")
    return url


def build_system_prompt(manifest: dict) -> str:
    """매니페스트에서 도구 목록을 읽어 시스템 프롬프트 구성"""
    try:
        tools = manifest.get("tools", {})
        skills = tools.get("skills", [])
        mcp = tools.get("mcp", [])
        
        prompt = """너는 투자 분석 에이전트 'Nexus'야.
사용자의 투자 질문에 대해 분석하고 권고해줘.

사용 가능한 도구:
"""
        # 스킬 목록 추가
        if skills:
            prompt += "\n[스킬]\n"
            for skill in skills:
                prompt += f"- {skill['name']}: {skill.get('description', '')}\n"
                for cap in skill.get("capabilities", []):
                    prompt += f"  - capability: {cap}\n"
        
        # MCP 도구 목록 추가
        if mcp:
            prompt += "\n[MCP 도구]\n"
            for tool in mcp:
                prompt += f"- {tool['name']}: {tool.get('description', '')}\n"
        
        prompt += """
작업 흐름:
1. 사용자의 질문을 분석하여 의도 파악
2. 관련 투자 원칙을 메모리에서 검색
3. 적절한 도구를 선택하여 Worker에 요청
4. 결과를 분석하여 최종 투자 권고 리포트 작성

항상 전문적이고 객관적인 자문을 제공해."""
        
        return prompt
    except Exception as e:
        logger.error(f"시스템 프롬프트 생성 오류: {e}")
        return "너는 투자 분석 에이전트야."


# ==================== 방어적 네트워크 클라이언트 ====================
class NetworkClient:
    """방어적 네트워크 클라이언트"""
    
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url
        self.timeout = timeout
        self.session: Optional[object] = None
    
    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입"""
        import aiohttp
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료"""
        if self.session:
            await self.session.close()
    
    async def post_with_retry(self, endpoint: str, payload: dict, 
                              max_retries: int = Config.MAX_RETRIES) -> Optional[dict]:
        """재시도 로직이 포함된 POST 요청"""
        import aiohttp
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with self.session.post(
                    f"{self.base_url}{endpoint}",
                    json=payload
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 404:
                        logger.error(f"엔드포인트를 찾을 수 없음: {endpoint}")
                        return None
                    elif resp.status >= 500:
                        logger.warning(f"서버 오류 ({resp.status}), 재시도 {attempt + 1}/{max_retries}")
                        last_error = f"Server error: {resp.status}"
                    else:
                        logger.error(f"HTTP 오류: {resp.status}")
                        return None
                        
            except aiohttp.ClientConnectorError as e:
                last_error = f"연결 실패: {e}"
                logger.warning(f"Worker 연결 실패, 재시도 {attempt + 1}/{max_retries}")
            except asyncio.TimeoutError:
                last_error = "요청 타임아웃"
                logger.warning(f"타임아웃, 재시도 {attempt + 1}/{max_retries}")
            except Exception as e:
                last_error = f"예상치 못한 오류: {e}"
                logger.error(f"예외 발생: {e}")
            
            # 재시도 전 대기
            if attempt < max_retries - 1:
                await asyncio.sleep(Config.RETRY_DELAY)
        
        logger.error(f"최대 재시도 횟수 초과: {last_error}")
        return None
    
    async def health_check(self) -> bool:
        """헬스 체크"""
        try:
            async with self.session.get(f"{self.base_url}/health") as resp:
                return resp.status == 200
        except Exception:
            return False


# ==================== 테스트 워크플로우 ====================
async def test_workflow():
    """전체 워크플로우 테스트 (방어적 코딩 적용)"""
    print("=" * 60)
    print("Nexus 시스템 테스트 시작")
    print("=" * 60)
    
    # 1. 매니페스트 로드
    print("\n[1] 매니페스트 로드...")
    manifest = load_manifest()
    print(f"    버전: {manifest.get('version')}")
    print(f"    이름: {manifest.get('name')}")
    
    # 2. 시스템 프롬프트 구성
    print("\n[2] 시스템 프롬프트 구성...")
    system_prompt = build_system_prompt(manifest)
    total_tools = len(manifest.get('tools', {}).get('skills', [])) + len(manifest.get('tools', {}).get('mcp', []))
    print(f"    사용 가능한 도구: {total_tools}개")
    
    # 3. Worker URL 확인
    print("\n[3] Worker 연결 설정...")
    worker_url = get_worker_url()
    print(f"    Worker URL: {worker_url}")
    os.environ["WORKER_URL"] = worker_url
    
    # 4. ManagerCore import 및 초기화
    print("\n[4] ManagerCore 초기화...")
    from manager.manager_core import ManagerCore
    
    try:
        manager = ManagerCore()
        print("    ✓ ManagerCore 준비 완료")
    except Exception as e:
        print(f"    ❌ ManagerCore 초기화 실패: {e}")
        logger.error(f"ManagerCore 초기화 오류: {e}")
        return
    
    # 5. Worker 연결 확인
    print("\n[5] Worker 연결 확인...")
    try:
        async with NetworkClient(worker_url, timeout=5) as client:
            if await client.health_check():
                print("    ✓ Worker 연결 정상")
            else:
                print("    ⚠ Worker 응답 없음 (계속 진행)")
    except Exception as e:
        print(f"    ⚠ Worker 연결 확인 실패: {e}")
        logger.warning(f"Worker 헬스 체크 실패: {e}")
    
    # 6. 테스트 질문 실행
    user_input = "애플(AAPL) 주가 기술적 분석 및 시장 분위기 종합해서 알려줘"
    print(f"\n[6] 테스트 질문 실행...")
    print(f"    질문: {user_input}")
    print("-" * 60)
    
    result = await safe_execute_workflow(manager, user_input, "test_user")
    
    # 결과 출력
    print("\n[결과]")
    print("-" * 60)
    
    if result.get("error"):
        print(f"❌ 오류: {result['error']}")
    else:
        # 적용된 원칙
        principles = result.get("applied_principles", [])
        if principles:
            print(f"\n📋 적용된 원칙 ({len(principles)}개):")
            for p in principles:
                print(f"   - {p.get('content', '')[:80]}...")
        
        # 워커 결과
        worker_result = result.get("worker_result")
        if worker_result:
            print(f"\n🔧 Worker 결과:")
            print(f"   상태: {worker_result.get('status', 'unknown')}")
        
        # 워커 요약
        worker_summary = result.get("worker_summary")
        if worker_summary:
            print(f"\n📝 Worker 요약:")
            print(f"   {worker_summary[:200]}...")
        
        # 최종 리포트
        final_report = result.get("final_report")
        if final_report:
            print(f"\n💎 최종 투자 리포트:")
            print("-" * 60)
            print(final_report)
            print("-" * 60)
        else:
            print("\n⚠ 최종 리포트 없음 (Worker 연결 실패 가능)")
    
    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)


async def safe_execute_workflow(manager, user_input: str, user_id: str) -> dict:
    """안전한 워크플로우 실행 (예외 처리 포함)"""
    try:
        result = await asyncio.wait_for(
            manager.run(user_input=user_input, user_id=user_id),
            timeout=Config.WORKER_TIMEOUT + Config.OLLAMA_TIMEOUT
        )
        return result
    except asyncio.TimeoutError:
        logger.error("워크플로우 타임아웃")
        return {
            "error": "작업 시간이 초과되었습니다. RTX 서버 연결을 확인해 주세요.",
            "applied_principles": [],
            "worker_result": None,
            "final_report": None
        }
    except ConnectionError as e:
        logger.error(f"연결 오류: {e}")
        return {
            "error": f"RTX 서버에 연결할 수 없습니다: {e}",
            "applied_principles": [],
            "worker_result": None,
            "final_report": None
        }
    except Exception as e:
        logger.error(f"예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
        return {
            "error": f"시스템 오류가 발생했습니다: {e}",
            "applied_principles": [],
            "worker_result": None,
            "final_report": None
        }


def main():
    """메인 함수"""
    # 중앙 설정 초기화
    url = NexusConfig.get_worker_url()
    rtx_ip = url.split("//")[-1].split(":")[0]
    os.environ["RTX_IP"] = rtx_ip
    print(f"시스템 설정 완료 (RTX IP: {rtx_ip})")
    
    # 비동기 테스트 실행
    try:
        asyncio.run(test_workflow())
    except KeyboardInterrupt:
        print("\n사용자에 의해 중단됨")
    except Exception as e:
        logger.error(f"메인 실행 오류: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
