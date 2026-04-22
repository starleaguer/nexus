import logging
import asyncio
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
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

from manager.manager_core import ManagerCore
from manager.researcher import ToolHunter
# AutonomousAgent import removed (moved to worker)
from shared.config_loader import NexusConfig
import ollama

# 로컬 워커 프로세스 관리
worker_process = None
core = ManagerCore()
hunter = ToolHunter()
# autonomous_agent moved to worker

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
    # NOTE: Autonomous agent moved to worker; server no longer starts it.
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
manager = core
memory = core.memory

# ==================== 모델 정의 ====================
class ChatRequest(BaseModel):
    query: str
    user_id: str = "web_user"

class ApproveRequest(BaseModel):
    tool_name: str

class ResearchRequest(BaseModel):
    query: str

class TimeoutConfigRequest(BaseModel):
    worker: int
    ollama: int

class IntervalConfigRequest(BaseModel):
    interval: int

class ModelConfigRequest(BaseModel):
    component: str  # "manager" or "worker"
    model: str

class YouTubeSummarizeRequest(BaseModel):
    url: str

class KnowledgeNoteRequest(BaseModel):
    content: str
    source_url: str = ""
    user_comment: str = ""
    category: str = "youtube"

# ==================== 엔드포인트 ====================

@app.get("/api/models")
async def get_models():
    """Proxy request to worker for Ollama model list"""
    worker_url = NexusConfig.get_worker_url()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        try:
            async with session.get(f"{worker_url}/models") as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=resp.status, detail="Worker models endpoint error")
                data = await resp.json()
                return data
        except Exception as e:
            logger.error(f"Failed to proxy models request: {e}")
            raise HTTPException(status_code=500, detail="Unable to retrieve models from worker")

@app.post("/api/config/model")
async def update_model_config(req: ModelConfigRequest):
    """시스템 모델 설정 업데이트 (proxy worker component)"""
    try:
        # Proxy updates for worker component
        if req.component == "worker":
            worker_url = NexusConfig.get_worker_url()
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.post(f"{worker_url}/api/config/model", json=req.dict()) as resp:
                    if resp.status != 200:
                        raise HTTPException(status_code=resp.status, detail="Worker model update failed")
                    return await resp.json()
        # Server-side handling for other components
        manifest = NexusConfig.load_manifest()
        if "models" not in manifest:
            manifest["models"] = {}
        manifest["models"][req.component] = req.model
        
        with open(NexusConfig.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✅ 매니페스트 업데이트 완료: {req.component} -> {req.model}")
        NexusConfig._manifest = None
        
        if req.component == "manager":
            manager.llm.model = req.model
            
        return {"status": "success", "message": f"{req.component} 모델이 {req.model}로 변경되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/research")
# Duplicate decorator removed
async def run_research(req: ResearchRequest):
    """Proxy research request to worker"""
    worker_url = NexusConfig.get_worker_url()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        payload = {"query": req.query}
        async with session.post(f"{worker_url}/api/research", json=payload) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=resp.status, detail="Worker research failed")
            return await resp.json()

@app.get("/api/learnings")
async def get_learnings():
    """에이전트 학습 로그 조회"""
    try:
        learnings = memory.get_all_learnings()
        return {"status": "success", "learnings": learnings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/youtube/summarize")
async def youtube_summarize(req: YouTubeSummarizeRequest):
    """유튜브 URL 추출 후 Multi-Agent 기반 고도화 요약"""
    try:
        import aiohttp
        from manager.manager_core import OllamaClient
        
        # 1. Worker에게 youtube_summarizer 스킬 실행 요청 (Metadata + Transcript/Whisper)
        worker_url = NexusConfig.get_worker_url()
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
            payload = {"tool_name": "youtube_summarizer", "params": {"url": req.url}}
            async with session.post(f"{worker_url}/execute", json=payload) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=resp.status, detail="Worker 오류")
                worker_result = await resp.json()

        raw = worker_result.get("raw_result", {})
        if raw.get("error"):
            return {"status": "error", "message": raw["error"]}

        transcript = raw.get("transcript", "")
        if not transcript:
            return {"status": "error", "message": "추출된 텍스트가 없습니다."}

        # 2. Multi-Agent 요약 파이프라인
        llm = OllamaClient()
        
        def chunk_text(text, size=4000):
            return [text[i:i+size] for i in range(0, len(text), size)]
            
        chunks = chunk_text(transcript)
        logger.info(f"YouTube transcript split into {len(chunks)} chunks.")

        # Agent 1: 핵심 팩트 추출
        extracted_facts = []
        extractor_system = "너는 데이터 추출가야. 스크립트에서 시청자 인사나 잡담은 무시하고 핵심 주장과 정보만 추출해줘."
        
        for i, chunk in enumerate(chunks):
            prompt = f"다음 스크립트에서 중요한 정보가 누락되지 않도록 명확하게 요약해 주세요:\n\n{chunk}"
            fact = llm.chat(extractor_system, prompt)
            extracted_facts.append(fact)
            
        combined_facts = "\n\n".join(extracted_facts)

        # Agent 2: 최종 구조화 요약 작성
        writer_system = "당신은 전문 에디터입니다. 추출된 핵심 팩트들을 바탕으로 지식 베이스용으로 구조화하여 완벽하게 요약 정리하는 AI 어시스턴트입니다."
        writer_prompt = f"""다음은 긴 영상 스크립트에서 추출된 핵심 팩트 데이터 모음입니다.
이를 바탕으로, 반드시 **한국어**로, 그리고 아래의 일관된 마크다운 구조를 엄격하게 지켜서 요약해 주세요.

---
### 📌 1. 핵심 요약 (Overview)
- 영상의 주제와 가장 중요한 결론을 2~3문장 이내로 직관적으로 요약하세요.

### 🔑 2. 주요 포인트 (Key Points)
- 영상의 핵심 내용 3~5가지를 글머리 기호(`-`)로 정리하세요.
- 각 포인트의 제목은 **굵은 글씨**로 강조하고, 간단한 부연 설명을 덧붙이세요.

### 📜 3. 세부 내용 (Detailed Summary)
- 논리적 흐름에 따라 전체 내용을 상세히 서술하세요. 중요한 키워드는 **굵게** 표시하세요.

### 💡 4. 인사이트 (Insights)
- 이 영상에서 얻을 수 있는 교훈이나 실무 적용 방안을 작성하세요.
---
[데이터]
{combined_facts}"""

        final_summary = llm.chat(writer_system, writer_prompt)
        
        return {
            "status": "success",
            "video_id": raw.get("video_id"),
            "url": req.url,
            "metadata": raw.get("metadata"),
            "method": raw.get("method"),
            "summary": final_summary
        }
    except Exception as e:
        logger.error(f"YouTube summarize error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/knowledge/note")
async def save_knowledge_note(req: KnowledgeNoteRequest):
    """지식 노트 저장"""
    try:
        memory.save_knowledge_note(
            content=req.content,
            source_url=req.source_url,
            user_comment=req.user_comment,
            category=req.category
        )
        return {"status": "success", "message": "AI가 이 내용을 학습했습니다!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/knowledge/notes")
async def get_knowledge_notes():
    """저장된 지식 노트 목록 조회"""
    try:
        notes = memory.get_knowledge_notes()
        return {"status": "success", "notes": notes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/autonomous/logs")
async def get_autonomous_logs():
    """자율 모니터링 로그 조회"""
    try:
        logs = memory.get_autonomous_logs()
        return {"status": "success", "logs": logs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/config/interval")
async def update_interval_config(req: IntervalConfigRequest):
    """자율 모니터링 주기 업데이트"""
    try:
        manifest = NexusConfig.load_manifest()
        if "autonomous" not in manifest:
            manifest["autonomous"] = {}
        
        manifest["autonomous"]["interval"] = req.interval
        
        with open(NexusConfig.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        NexusConfig._manifest = None
        
        # 주기가 변경되었으므로 자율 루프 재시작
        autonomous_agent.stop()
        autonomous_agent.start()
        
        return {"status": "success", "message": f"모니터링 주기가 {req.interval}초로 업데이트되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/config/timeout")
async def update_timeout_config(req: TimeoutConfigRequest):
    """시스템 타임아웃 설정 업데이트"""
    try:
        manifest = NexusConfig.load_manifest()
        if "timeouts" not in manifest:
            manifest["timeouts"] = {}
        
        manifest["timeouts"]["worker"] = req.worker
        manifest["timeouts"]["ollama"] = req.ollama
        
        with open(NexusConfig.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        NexusConfig._manifest = None
        
        return {"status": "success", "message": "타임아웃 설정이 업데이트되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return "<h1>Nexus Dashboard</h1><p>UI files not found.</p>"
    with open(index_file, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/status")
async def get_status():
    """시스템 상태 확인"""
    manifest = NexusConfig.load_manifest()
    return {
        "status": "online",
        "manager_model": NexusConfig.get_model("manager"),
        "worker_model": NexusConfig.get_model("worker"),
        "timeouts": manifest.get("timeouts", {"worker": 120, "ollama": 120}),
        "autonomous": manifest.get("autonomous", {"interval": 3600}),
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
        msg = hunter.approve_candidate(req.tool_name)
        return {"status": "success", "message": msg}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/reject")
async def reject_tool(req: ApproveRequest):
    """후보 도구 거절"""
    success = hunter.reject_candidate(req.tool_name)
    if success:
        return {"status": "success", "message": f"'{req.tool_name}' 거절 완료."}
    else:
        raise HTTPException(status_code=404, detail="도구를 찾을 수 없습니다.")

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
