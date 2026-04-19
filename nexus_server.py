import logging
import asyncio
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from manager.manager_core import ManagerCore
from manager.researcher import ToolHunter
from shared.config_loader import NexusConfig
import ollama

from contextlib import asynccontextmanager

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 로컬 워커 프로세스 관리
worker_process = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: 로컬 모드일 경우 워커 자동 실행
    global worker_process
    manifest = NexusConfig.load_manifest()
    mode = manifest.get("worker", {}).get("mode", "remote")
    
    if mode == "local":
        logger.info("🚀 로컬 모드 감지: 로컬 워커(Worker API)를 자동으로 시작합니다...")
        try:
            worker_process = await asyncio.create_subprocess_exec(
                "uv", "run", "python", "worker/worker_api.py",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            logger.info(f"✅ 로컬 워커 시작됨 (PID: {worker_process.pid})")
        except Exception as e:
            logger.error(f"❌ 로컬 워커 시작 실패: {e}")
            
    yield
    
    # Shutdown: 서버 종료 시 워커도 함께 종료
    if worker_process:
        logger.info("🛑 로컬 워커를 종료하는 중...")
        worker_process.terminate()
        await worker_process.wait()
        logger.info("✅ 로컬 워커 종료 완료.")

app = FastAPI(title="Nexus Hub Dashboard", lifespan=lifespan)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 스태틱 파일 설정 (UI)
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 초기화
manager = ManagerCore()
hunter = ToolHunter()

# ==================== 모델 정의 ====================
class ChatRequest(BaseModel):
    query: str
    user_id: str = "web_user"

class ApproveRequest(BaseModel):
    tool_name: str

class ResearchRequest(BaseModel):
    query: str

class ModelConfigRequest(BaseModel):
    component: str  # "manager" or "worker"
    model: str

# ==================== 엔드포인트 ====================

@app.get("/api/models")
async def get_models():
    """Ollama에 설치된 모델 목록 반환"""
    try:
        models_info = ollama.list()
        return [m.model for m in models_info.models]
    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        return ["gemma4:26b", "gemma4:e4b", "gemma4:31b"] # Fallback

@app.post("/api/config/model")
async def update_model_config(req: ModelConfigRequest):
    """시스템 모델 설정 업데이트"""
    try:
        manifest = NexusConfig.load_manifest()
        if "models" not in manifest:
            manifest["models"] = {}
        
        manifest["models"][req.component] = req.model
        
        # manifest.json 저장
        with open(NexusConfig.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        # 전역 캐시 초기화 (다음 호출 시 로드되도록)
        NexusConfig._manifest = None
        
        # ManagerCore 인스턴스 업데이트 (새 모델 적용)
        if req.component == "manager":
            manager.llm.model = req.model
            
        return {"status": "success", "message": f"{req.component} 모델이 {req.model}로 변경되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/research")
async def run_research(req: ResearchRequest):
    """맞춤형 도구 탐색 실행"""
    try:
        logger.info(f"Custom research requested: {req.query}")
        # 비동기로 실행하고 일단 접수 알림 (탐색은 시간이 걸리므로)
        asyncio.create_task(hunter.run_research_cycle([req.query]))
        return {"status": "success", "message": f"'{req.query}' 분야의 도구를 탐색하기 시작했습니다. 잠시 후 후보 목록을 확인하세요."}
    except Exception as e:
        logger.error(f"Research error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return "<h1>Nexus Dashboard</h1><p>UI files not found. Please create static/index.html</p>"
    with open(index_file, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/status")
async def get_status():
    """시스템 상태 반환"""
    manifest = NexusConfig.load_manifest()
    return {
        "version": manifest.get("version"),
        "manager_model": NexusConfig.get_model("manager"),
        "worker_model": NexusConfig.get_model("worker"),
        "worker_url": NexusConfig.get_worker_url(),
        "active_tools_count": len(manifest.get("tools", {}).get("skills", [])) + len(manifest.get("tools", {}).get("mcp", []))
    }

@app.get("/api/candidates")
async def get_candidates():
    """후보 도구 목록 반환"""
    return hunter._load_candidates()

@app.post("/api/approve")
async def approve_tool(req: ApproveRequest):
    """도구 승인"""
    try:
        result = hunter.approve_candidate(req.tool_name)
        return {"status": "success", "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tools")
async def get_active_tools():
    """현재 활성화된 도구 목록 반환"""
    manifest = NexusConfig.load_manifest()
    return manifest.get("tools", {})

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """에이전트 질의 실행"""
    try:
        logger.info(f"Chat request received: {req.query}")
        result = await manager.run(req.query, req.user_id)
        return result
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
