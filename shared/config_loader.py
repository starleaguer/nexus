import os
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# 프로젝트 루트 경로 계산
SHARED_DIR = Path(__file__).parent
PROJECT_ROOT = SHARED_DIR.parent
MANIFEST_PATH = SHARED_DIR / "manifest.json"

class NexusConfig:
    """Nexus 시스템 전체 설정 관리자"""
    
    MANIFEST_PATH = MANIFEST_PATH
    _manifest = None

    @classmethod
    def load_manifest(cls):
        """매니페스트 파일을 로드합니다."""
        if cls._manifest is not None:
            return cls._manifest
        
        try:
            if MANIFEST_PATH.exists():
                with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                    cls._manifest = json.load(f)
            else:
                logger.warning(f"매니페스트 파일을 찾을 수 없습니다: {MANIFEST_PATH}")
                cls._manifest = {}
        except Exception as e:
            logger.error(f"매니페스트 로드 중 오류 발생: {e}")
            cls._manifest = {}
        
        return cls._manifest

    @classmethod
    def get_model(cls, component: str, default: str = None) -> str:
        """컴포넌트(manager, worker)별 모델명을 가져옵니다."""
        manifest = cls.load_manifest()
        env_key = f"{component.upper()}_MODEL"
        
        # 1. 환경 변수 우선
        model = os.getenv(env_key)
        if model:
            return model
            
        # 2. 매니페스트 확인
        model = manifest.get("models", {}).get(component)
        if model:
            return model
            
        # 3. 기본값 반환
        return default or ("gemma2:27b" if component == "manager" else "gemma2:9b")

    @classmethod
    def get_worker_url(cls) -> str:
        """Worker 서버의 URL을 가져옵니다."""
        # 1. 환경 변수 우선
        url = os.getenv("WORKER_URL")
        if url:
            return url
            
        manifest = cls.load_manifest()
        worker_cfg = manifest.get("worker", {})
        
        ip = os.getenv("RTX_IP", worker_cfg.get("ip", "127.0.0.1"))
        port = os.getenv("RTX_PORT", worker_cfg.get("port", 8000))
        
        return f"http://{ip}:{port}"

    @classmethod
    def get_manager_url(cls) -> str:
        """Manager 서버의 URL을 가져옵니다."""
        return os.getenv("MANAGER_URL", "http://localhost:9000")

    @classmethod
    def get_path(cls, key: str, default: str) -> str:
        """매니페스트 또는 환경 변수에서 경로 설정을 가져옵니다."""
        manifest = cls.load_manifest()
        # manager.vector_store_path 등 중첩된 키 처리
        parts = key.split('.')
        val = manifest
        for part in parts:
            if isinstance(val, dict):
                val = val.get(part)
            else:
                val = None
                break
        
        env_key = key.replace('.', '_').upper()
        return os.getenv(env_key, val or default)

# 사용 편의를 위한 인스턴스/상수 제공
def get_config():
    NexusConfig.load_manifest()
    return NexusConfig
