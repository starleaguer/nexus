"""
Worker API - RTX 데스크탑에서 실행되는 FastAPI 서버
"""
import importlib
import sys
import os
from pathlib import Path
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import ollama
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 프로젝트 루트를 sys.path에 추가하여 shared 모듈 등을 찾을 수 있게 함
PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.config_loader import NexusConfig

# ==================== 설정 ====================
class Config:
    """Worker 설정 관리 (중앙 로더 사용)"""
    PROJECT_ROOT = NexusConfig.PROJECT_ROOT
    MANIFEST_PATH = NexusConfig.MANIFEST_PATH
    
    @property
    def WORKER_MODEL(self):
        return NexusConfig.get_model("worker")
    
    @property
    def MANAGER_URL(self):
        return NexusConfig.get_manager_url()
    
    @property
    def HOST(self):
        return NexusConfig.get_path("worker.host", "0.0.0.0")
    
    @property
    def PORT(self):
        url = NexusConfig.get_worker_url()
        return int(url.split(":")[-1])

# 설정 인스턴스 생성
config = Config()

# 스킬 디렉토리
SKILLS_DIR = Path(__file__).parent / "skills"

# 등록된 스킬 로드
SKILLS_REGISTRY = {}


def load_manifest():
    """매니페스트 로드 (중앙 로더 사용)"""
    return NexusConfig.load_manifest()


def discover_skills():
    """skills 디렉토리에서 사용 가능한 스킬 발견"""
    if not SKILLS_DIR.exists():
        return
    
    # 프로젝트 루트를 sys.path에 추가하여 모듈 로드 경로 설정
    project_root = str(Path(__file__).parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)



    for py_file in SKILLS_DIR.glob("*.py"):
        if py_file.stem == "__init__":
            continue
        
        # 비활성화: borsa_mcp 스킬은 로드하지 않음
        if py_file.stem == "borsa_mcp":
            # skip loading this skill to avoid ImportError
            continue

        module_name = f"worker.skills.{py_file.stem}"
        try:
            # 모듈 동적 로드
            module = importlib.import_module(module_name)
            
            # run 함수 또는 Skill 클래스 확인
            if hasattr(module, "run"):
                SKILLS_REGISTRY[py_file.stem] = {
                    "name": py_file.stem,
                    "module": module,
                    "type": "function"
                }
            elif hasattr(module, "Skill"):
                SKILLS_REGISTRY[py_file.stem] = {
                    "name": py_file.stem,
                    "module": module,
                    "type": "class"
                }
        except Exception as e:
            print(f"Failed to load skill {py_file.stem}: {e}")


# Lifespan 이벤트 핸들러
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    manifest = load_manifest()
    discover_skills()
    print(f"Loaded skills: {list(SKILLS_REGISTRY.keys())}")
    yield
    # Shutdown (optional)


app = FastAPI(title="Nexus Worker API", lifespan=lifespan)

# CORS 설정 - 외부(Mac)からの接続を許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # すべてのOriginsを許可（本番では制限推奨）
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def execute_skill(skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """스킬 실행"""
    if skill_name not in SKILLS_REGISTRY:
        raise ValueError(f"Skill not found: {skill_name}")
    
    skill_info = SKILLS_REGISTRY[skill_name]
    module = skill_info["module"]
    
    if skill_info["type"] == "function":
        # 함수형 스킬 실행
        return module.run(params)
    elif skill_info["type"] == "class":
        # 클래스형 스킬 실행
        skill_instance = module.Skill()
        if hasattr(skill_instance, "execute"):
            return skill_instance.execute(params)
        elif hasattr(skill_instance, "run"):
            return skill_instance.run(params)
    
    raise ValueError(f"Skill {skill_name} has no executable method")


def summarize_with_ollama(raw_result: Dict[str, Any]) -> str:
    """Ollama로 결과 요약"""
    try:
        result_text = json.dumps(raw_result, ensure_ascii=False, indent=2)
        
        prompt = f"""다음 작업 실행 결과를 핵심만 요약해줘:

{result_text}

요약 형식:
- 주요 결과: 
- 핵심 인사이트: 
- 다음 단계 제안: 
"""
        
        response = ollama.chat(
            model=config.WORKER_MODEL,  # 인스턴스 설정 사용
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response["message"]["content"]
    except Exception as e:
        print(f"Ollama 요약 실패: {e}")
        return f"요약 실패 (원본 결과): {json.dumps(raw_result, ensure_ascii=False)}"


class TaskRequest(BaseModel):
    tool_name: str
    params: Dict[str, Any]
    task_id: Optional[str] = None
    callback_url: Optional[str] = None
    summarize: bool = True  # Ollama 요약 여부


class TaskResponse(BaseModel):
    task_id: Optional[str]
    status: str
    raw_result: Optional[Dict[str, Any]] = None
    summary: Optional[str] = None
    error: Optional[str] = None


@app.get("/health")
async def health():
    """헬스 체크"""
    return {
        "status": "healthy",
        "skills": list(SKILLS_REGISTRY.keys()),
        "ollama_available": _check_ollama()
    }


def _check_ollama() -> bool:
    """Ollama 가용성 확인"""
    try:
        ollama.list()
        return True
    except:
        return False


@app.get("/skills")
async def list_skills():
    """사용 가능한 스킬 목록"""
    return {
        "skills": [
            {"name": name, "type": info["type"]}
            for name, info in SKILLS_REGISTRY.items()
        ]
    }


@app.get("/models")
async def list_models():
    """
    Ollama에 등록된 모델 리스트를 반환합니다.
    Ollama가 로컬에 설치돼 있어야 합니다.
    """
    try:
        # ollama.list() 는 현재 사용 가능한 모델 정보를 반환합니다.
        resp = ollama.list()
        # 리스트 형태이든 객체 형태이든 처리
        if isinstance(resp, dict):
            models_data = resp.get("models", [])
        else:
            # newer versions of ollama lib might return a ListResponse object
            models_data = getattr(resp, "models", [])
            
        model_names = [m.get("model") if isinstance(m, dict) else getattr(m, "model", str(m)) for m in models_data]
        return model_names
    except Exception as e:
        logger.error(f"Ollama 모델 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve Ollama models")

@app.post("/execute", response_model=TaskResponse)
async def execute_task(task: TaskRequest):
    """스킬 실행 엔드포인트"""
    if task.tool_name not in SKILLS_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Skill not found: {task.tool_name}")
    
    try:
        # 1. 스킬 실행
        raw_result = execute_skill(task.tool_name, task.params)
        
        # 2. Ollama로 요약 (요청 시)
        summary = None
        if task.summarize and _check_ollama():
            summary = summarize_with_ollama(raw_result)
        
        return TaskResponse(
            task_id=task.task_id,
            status="completed",
            raw_result=raw_result,
            summary=summary
        )
        
    except Exception as e:
        return TaskResponse(
            task_id=task.task_id,
            status="failed",
            error=str(e)
        )


@app.post("/execute/raw", response_model=TaskResponse)
async def execute_task_raw(task: TaskRequest):
    """요약 없이 원본 결과만 반환"""
    if task.tool_name not in SKILLS_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Skill not found: {task.tool_name}")
    
    try:
        raw_result = execute_skill(task.tool_name, task.params)
        return TaskResponse(
            task_id=task.task_id,
            status="completed",
            raw_result=raw_result
        )
    except Exception as e:
        return TaskResponse(
            task_id=task.task_id,
            status="failed",
            error=str(e)
        )


class ModelConfigRequest(BaseModel):
    component: str  # "manager" or "worker"
    model: str


@app.post("/api/config/model")
async def update_model_config(req: ModelConfigRequest):
    """Worker의 모델 설정 업데이트 및 매니페스트 저장"""
    try:
        manifest = load_manifest()
        if "models" not in manifest:
            manifest["models"] = {}
        
        # worker 컴포넌트인 경우만 업데이트 (혹은 전체 허용)
        manifest["models"][req.component] = req.model
        
        # NexusConfig.MANIFEST_PATH 에 저장
        with open(NexusConfig.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✅ [Worker] 매니페스트 업데이트 완료: {req.component} -> {req.model}")
        # 캐시 초기화 (shared config_loader 내부 로직이 있다면)
        NexusConfig._manifest = None
        
        return {"status": "success", "message": f"Worker가 {req.component} 모델을 {req.model}로 업데이트했습니다."}
    except Exception as e:
        logger.error(f"Worker model update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT
    )