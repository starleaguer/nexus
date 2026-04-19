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

# 매니페스트에서 모델 로드
PROJECT_ROOT = Path(__file__).parent.parent
with open(PROJECT_ROOT / "shared" / "manifest.json", encoding='utf-8') as f:
    _MANIFEST = json.load(f)
WORKER_MODEL = _MANIFEST.get("models", {}).get("worker", "gemma2:9b")

# 매니저 연결 정보
MANAGER_URL = os.getenv("MANAGER_URL", "http://localhost:9000")

# 스킬 디렉토리
SKILLS_DIR = Path(__file__).parent / "skills"

# 등록된 스킬 로드
SKILLS_REGISTRY = {}


def load_manifest():
    """매니페스트에서 스킬 로드"""
    manifest_path = os.path.join(os.path.dirname(__file__), "../shared/manifest.json")
    with open(manifest_path, "r", encoding='utf-8') as f:
        return json.load(f)


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
            model=WORKER_MODEL,  # 매니페스트에서 로드
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


if __name__ == "__main__":
    import uvicorn
    manifest = load_manifest()
    worker_config = manifest.get("worker", {})
    uvicorn.run(
        app,
        host=worker_config.get("host", "0.0.0.0"),  # 외부 접속 허용
        port=worker_config.get("port", 8000)
    )