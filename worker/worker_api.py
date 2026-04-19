"""
Worker API - RTX 데스크탑에서 실행되는 FastAPI 서버
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import json
import os

app = FastAPI(title="Nexus Worker API")

# 매니저 연결 정보
MANAGER_URL = os.getenv("MANAGER_URL", "http://localhost:9000")

# 등록된 스킬 로드
SKILLS_REGISTRY = {}


def load_manifest():
    """매니페스트에서 스킬 로드"""
    manifest_path = os.path.join(os.path.dirname(__file__), "../shared/manifest.json")
    with open(manifest_path, "r") as f:
        return json.load(f)


@app.on_event("startup")
async def startup():
    """시작 시 스킬 로드"""
    manifest = load_manifest()
    for skill in manifest.get("tools", {}).get("skills", []):
        SKILLS_REGISTRY[skill["name"]] = skill
    print(f"Loaded skills: {list(SKILLS_REGISTRY.keys())}")


class TaskRequest(BaseModel):
    task_id: str
    skill_name: str
    input_data: Dict[str, Any]
    callback_url: Optional[str] = None


class TaskResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@app.get("/health")
async def health():
    """헬스 체크"""
    return {"status": "healthy", "skills": list(SKILLS_REGISTRY.keys())}


@app.get("/skills")
async def list_skills():
    """사용 가능한 스킬 목록"""
    return {"skills": list(SKILLS_REGISTRY.values())}


@app.post("/execute", response_model=TaskResponse)
async def execute_task(task: TaskRequest):
    """스킬 실행"""
    if task.skill_name not in SKILLS_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Skill not found: {task.skill_name}")
    
    try:
        # 스킬 실행 로직 (동적으로 로드)
        result = {"status": "completed", "output": f"Executed {task.skill_name}"}
        return TaskResponse(task_id=task.task_id, status="completed", result=result)
    except Exception as e:
        return TaskResponse(task_id=task.task_id, status="failed", error=str(e))


if __name__ == "__main__":
    import uvicorn
    manifest = load_manifest()
    worker_config = manifest.get("worker", {})
    uvicorn.run(app, host=worker_config.get("host", "0.0.0.0"), port=worker_config.get("port", 8000))