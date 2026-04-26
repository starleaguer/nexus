import os
import json
import ast
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# 프로젝트 루트 경로 계산
CORE_DIR = Path(__file__).parent
PROJECT_ROOT = CORE_DIR.parent
MANIFEST_PATH = PROJECT_ROOT / "manifest.json"

class NexusConfig:
    """Nexus 시스템 전체 설정 관리자"""
    
    PROJECT_ROOT = PROJECT_ROOT
    MANIFEST_PATH = MANIFEST_PATH
    _manifest = None

    @classmethod
    def load_manifest(cls):
        """매니페스트 파일을 로드합니다. (실시간 반영을 위해 캐시를 사용하지 않습니다)"""
        try:
            if MANIFEST_PATH.exists():
                with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            else:
                logger.warning(f"매니페스트 파일을 찾을 수 없습니다: {MANIFEST_PATH}")
                return {}
        except Exception as e:
            logger.error(f"매니페스트 로드 중 오류 발생: {e}")
            return {}

    @classmethod
    def get_model(cls, component: str, default: str = None) -> str:
        """컴포넌트(core, worker)별 모델명을 가져옵니다."""
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
        return default or ("gemma2:27b" if component in ["manager", "core"] else "gemma2:9b")

    @classmethod
    def get_worker_url(cls) -> str:
        """Worker 서버의 URL을 가져옵니다. (IP가 없으면 기본 127.0.0.1)"""
        # 1. 환경 변수 우선
        url = os.getenv("WORKER_URL")
        if url:
            return url
            
        manifest = cls.load_manifest()
        worker_cfg = manifest.get("worker", {})
        
        # 2. 매니페스트 또는 환경변수에서 IP/Port 확인 (기본값: 로컬)
        ip = os.getenv("RTX_IP", worker_cfg.get("ip", "127.0.0.1"))
        port = os.getenv("RTX_PORT", worker_cfg.get("port", 11434))
        
        return f"http={ip}:{port}".replace("http=", "http://") # f-string 안전 처리

    @classmethod
    def get_core_url(cls) -> str:
        """Core 서버의 URL을 가져옵니다."""
        return os.getenv("CORE_URL", os.getenv("MANAGER_URL", "http://localhost:8080"))

    @classmethod
    def get_path(cls, key: str, default: str) -> str:
        """매니페스트 또는 환경 변수에서 경로 설정을 가져옵니다."""
        manifest = cls.load_manifest()
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

    @classmethod
    def get_timeout(cls, key: str, default: int) -> int:
        """타임아웃 설정을 가져옵니다."""
        manifest = cls.load_manifest()
        val = manifest.get("timeouts", {}).get(key)
        env_key = f"{key.upper()}_TIMEOUT"
        return int(os.getenv(env_key, val or default))

    @classmethod
    def get_discovered_skills(cls) -> list:
        """skills/ 폴더를 스캔하여 자동으로 스킬 목록과 설명을 추출합니다. (Zero-Config)"""
        skills_dir = cls.PROJECT_ROOT / "skills"
        discovered = []
        if not skills_dir.exists():
            return discovered

        for file_path in skills_dir.glob("*.py"):
            if file_path.name.startswith("__"):
                continue
                
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=file_path.name)
                
                # run 함수가 있는지 확인
                has_run = any(isinstance(node, ast.FunctionDef) and node.name == "run" for node in tree.body)
                if not has_run:
                    continue
                    
                # 최상단 Docstring 추출
                docstring = ast.get_docstring(tree)
                description = docstring.strip().split('\n')[0] if docstring else "자동 탐색된 스킬 (설명 없음)"
                
                discovered.append({
                    "name": file_path.stem,
                    "description": description
                })
            except Exception as e:
                logger.warning(f"스킬 스캔 실패 ({file_path.name}): {e}")
                
        return discovered

# 사용 편의를 위한 인스턴스/상수 제공
def get_config():
    NexusConfig.load_manifest()
    return NexusConfig
