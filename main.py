import os
import logging
import asyncio
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import aiohttp

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 외부 라이브러리 로그 억제
logging.getLogger("httpx").setLevel(logging.WARNING)

from core.manager_core import ManagerCore
from core.autonomous_agent import AutonomousAgent
from core.config_loader import NexusConfig
import core.youtube_utils as yt_utils
import ollama

# 전역 인스턴스
core = ManagerCore()
autonomous_agent = AutonomousAgent(core)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 사용자가 PC에서 'ollama serve'를 실행한 상태라고 가정합니다.
    # 워커 연결 체크
    logger.info("🚀 Nexus Hub Server starting...")
    
    is_online = await core.llm.check_health()
    if is_online:
        logger.info(f"✅ Remote Worker is ONLINE at {core.llm.remote_url}")
    else:
        logger.warning(f"❌ Remote Worker is OFFLINE at {core.llm.remote_url}. Using local fallback for all tasks.")

    # 자율 모드 시작
    autonomous_agent.start()
    
    yield
    
    # 종료 시 자율 모드 중지
    autonomous_agent.stop()
    logger.info("🛑 Nexus Hub Server shutting down...")

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

# ==================== 모델 정의 ====================
class ChatRequest(BaseModel):
    query: str
    user_id: str = "web_user"

class ResearchRequest(BaseModel):
    query: str

class ModelConfigRequest(BaseModel):
    component: str  # "core" or "worker"
    model: str

class TimeoutConfigRequest(BaseModel):
    component: str # "worker" or "ollama"
    timeout: int

class IntervalConfigRequest(BaseModel):
    interval: int

class BulkDeleteRequest(BaseModel):
    ids: List[str]

class KnowledgeNoteRequest(BaseModel):
    content: str
    source_url: str = ""
    user_comment: str = ""
    category: str = "general"

class ApproveRequest(BaseModel):
    task_id: str

class YouTubeSummarizeRequest(BaseModel):
    url: str
    model_type: str = "local" # "local", "worker", "gemini"

# ==================== 엔드포인트 ====================

@app.get("/api/models/core")
@app.get("/api/models/manager") # Alias for compatibility
async def get_core_models():
    try:
        resp = ollama.list()
        models_data = getattr(resp, 'models', resp.get("models", resp) if isinstance(resp, dict) else resp)
        return [m.get("model") if isinstance(m, dict) else getattr(m, 'model', str(m)) for m in models_data]
    except:
        return ["gemma2:27b", "gemma2:9b"]

@app.get("/api/models/worker")
async def get_worker_models():
    """PC Ollama의 모델 목록 조회 (오프라인 시 로컬 폴백)"""
    # 헬스 체크 결과에 따라 URL 결정
    worker_url = core.llm.remote_url if core.llm.worker_available else "http://127.0.0.1:11434"
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(f"{worker_url}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = data.get("models", [])
                    return [m.get("name") for m in models]
                return ["gemma2:9b (PC Offline)"]
    except Exception as e:
        # 워커가 꺼져있으면 로컬 모델 목록이라도 가져옴
        try:
            resp = ollama.list()
            models_data = getattr(resp, 'models', resp.get("models", resp) if isinstance(resp, dict) else resp)
            return [m.get("model") if isinstance(m, dict) else getattr(m, 'model', str(m)) for m in models_data]
        except:
            return ["gemma2:9b (Fallback)"]

@app.post("/api/config/model")
async def update_model_config(req: ModelConfigRequest):
    try:
        manifest = NexusConfig.load_manifest()
        if "models" not in manifest: manifest["models"] = {}
        manifest["models"][req.component] = req.model
        with open(NexusConfig.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        NexusConfig._manifest = None
        
        # 모델 변경 시 에이전트 재시작 (새 모델 적용)
        autonomous_agent.stop()
        autonomous_agent.start()
        
        return {"status": "success", "message": f"{req.component} 모델이 {req.model}로 업데이트되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/config/timeout")
async def update_timeout_config(req: TimeoutConfigRequest):
    try:
        manifest = NexusConfig.load_manifest()
        if "timeouts" not in manifest: manifest["timeouts"] = {}
        manifest["timeouts"][req.component] = req.timeout
        with open(NexusConfig.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        return {"status": "success", "message": "타임아웃 설정이 업데이트되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/config/interval")
async def update_interval_config(req: IntervalConfigRequest):
    try:
        manifest = NexusConfig.load_manifest()
        if "autonomous" not in manifest: manifest["autonomous"] = {}
        manifest["autonomous"]["interval"] = req.interval
        with open(NexusConfig.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        # 주기 변경 시 에이전트 재시작
        autonomous_agent.stop()
        autonomous_agent.start()
        return {"status": "success", "message": "모니터링 주기가 업데이트되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/research")
async def run_research(req: ResearchRequest):
    """서버에서 모든 도구를 직접 실행하는 연구 워크플로우 시작"""
    try:
        result = await core.run(req.query)
        return result
    except Exception as e:
        logger.error(f"Research error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/learnings")
async def get_learnings():
    return {"status": "success", "learnings": core.memory.get_all_learnings()}

@app.post("/api/learnings/delete-bulk")
async def delete_learnings_bulk(req: BulkDeleteRequest):
    if core.memory.delete_learnings(req.ids):
        return {"status": "success"}
    return {"status": "error"}

@app.get("/api/knowledge/notes")
async def get_knowledge_notes(limit: int = 20):
    notes = core.memory.get_knowledge_notes(limit=limit)
    return {"status": "success", "notes": notes}

@app.post("/api/knowledge/note")
async def save_knowledge_note(req: KnowledgeNoteRequest):
    core.memory.save_knowledge_note(
        content=req.content,
        source_url=req.source_url,
        user_comment=req.user_comment,
        category=req.category
    )
    return {"status": "success"}

@app.get("/api/autonomous/logs")
async def get_autonomous_logs():
    """자율 에이전트의 활동 로그 반환"""
    return {"status": "success", "logs": autonomous_agent.get_logs()}

@app.post("/api/autonomous/logs/delete-bulk")
async def delete_autonomous_logs_bulk(req: BulkDeleteRequest):
    if core.memory.delete_autonomous_logs(req.ids):
        return {"status": "success"}
    return {"status": "error"}

@app.post("/api/approve")
async def approve_task(req: ApproveRequest):
    # 실제 시스템에선 해당 작업을 승인 처리하는 로직이 필요함
    return {"status": "success", "message": f"작업 {req.task_id} 승인됨"}

@app.post("/api/reject")
async def reject_task(req: ApproveRequest):
    return {"status": "success", "message": f"작업 {req.task_id} 거절됨"}

@app.get("/api/autonomous/reports")
async def get_autonomous_reports(limit: int = 20):
    """저장된 자율 분석 리포트 반환"""
    reports = core.memory.get_autonomous_logs(limit=limit)
    return {"status": "success", "reports": reports}

@app.get("/api/candidates")
async def get_candidates():
    """분석 후보 목록 (현재는 빈 목록 반환하여 에러 방지)"""
    return {"status": "success", "candidates": []}

@app.post("/api/youtube/summarize")
async def youtube_summarize(req: YouTubeSummarizeRequest):
    """유튜브 요약 (분산 LLM 활용)"""
    try:
        video_id = yt_utils.extract_video_id(req.url)
        if not video_id: return {"status": "error", "message": "유효하지 않은 URL"}
        
        metadata = yt_utils.get_yt_metadata(req.url)
        result = yt_utils.get_yt_transcript(video_id)
        
        if "error" in result: 
            result = await yt_utils.transcribe_audio_whisper(req.url)
            
        if "error" in result: 
            return {"status": "error", "message": f"자막 추출 실패: {result.get('error')}"}
        
        transcript = result["text"]
        chunks = [transcript[i:i+4000] for i in range(0, len(transcript), 4000)]
        
        # 1. 고속 작업: Worker LLM을 사용하여 파편화된 요약/추출 수행
        extracted_facts = []
        for chunk in chunks:
            # use_remote=True (Worker)
            fact = await core.llm.chat("너는 정보 추출가야. 핵심 내용만 요약해줘.", chunk, use_remote=(req.model_type=="worker"))
            extracted_facts.append(fact)
        
        combined_facts = "\n\n".join(extracted_facts)
        
        # 2. 깊은 추론: Manager LLM을 사용하여 최종 리포트 구성
        writer_system = "너는 유튜브 스크립트 요약 전문가야. 마크다운 구조로 한국어 요약해줘."
        writer_prompt = f"다음 내용을 바탕으로 요약해줘:\n{combined_facts}"
        
        final_summary = await core.llm.chat(writer_system, writer_prompt, use_remote=False)
        
        return {
            "status": "success",
            "metadata": metadata,
            "summary": final_summary
        }
    except Exception as e:
        logger.error(f"YouTube summarize error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists(): return "<h1>Nexus Dashboard</h1>"
    with open(index_file, "r", encoding="utf-8") as f: return f.read()

@app.get("/api/status")
async def get_status():
    manifest = NexusConfig.load_manifest()
    # 헬스 체크 기반 실시간 워커 주소
    actual_worker_url = core.llm.remote_url if core.llm.worker_available else "http://127.0.0.1:11434"
    
    return {
        "status": "online",
        "worker_online": core.llm.worker_available,
        "core_model": NexusConfig.get_model("core"),
        "worker_model": NexusConfig.get_model("worker"),
        "worker_url": actual_worker_url,
        "autonomous": {
            "interval": manifest.get("autonomous", {}).get("interval", 3600)
        },
        "mode": "consolidated"
    }

@app.get("/api/config")
async def get_system_config():
    """시스템 전체 설정(manifest) 반환 (오프라인 시 실시간 상태 반영)"""
    manifest = NexusConfig.load_manifest()
    
    # 워커가 오프라인이면 설정 화면에서도 로컬로 표시
    if not core.llm.worker_available:
        if "worker" not in manifest: manifest["worker"] = {}
        manifest["worker"]["ip"] = "127.0.0.1"
        manifest["worker"]["status"] = "offline (using local fallback)"
    else:
        if "worker" in manifest:
            manifest["worker"]["status"] = "online"
            
    return manifest

@app.get("/api/tools")
async def get_active_tools():
    manifest = NexusConfig.load_manifest()
    return manifest.get("tools", {})

@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        return await core.run(req.query, req.user_id)
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def kill_port(port):
    """지정한 포트를 사용 중인 프로세스를 찾아 종료합니다."""
    import subprocess
    import signal
    try:
        # lsof 명령어로 포트를 사용하는 PID 찾기
        result = subprocess.check_output(["lsof", "-t", f"-i:{port}"])
        pids = result.decode().split()
        for pid in pids:
            pid = int(pid)
            if pid == os.getpid():
                continue
            logger.info(f"♻️ 포트 {port}를 사용 중인 기존 프로세스({pid})를 종료하고 재시작합니다.")
            os.kill(pid, signal.SIGKILL)
        import time
        time.sleep(1) # 포트가 완전히 해제될 때까지 잠시 대기
    except subprocess.CalledProcessError:
        # 해당 포트를 사용하는 프로세스가 없는 경우
        pass
    except Exception as e:
        logger.error(f"⚠️ 포트 정리 중 오류 발생: {e}")

if __name__ == "__main__":
    import uvicorn
    PORT = 8080
    kill_port(PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
