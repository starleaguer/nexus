import os
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

from core.manager_core import ManagerCore, AgentState
from core.researcher import ToolHunter
from core.autonomous_agent import AutonomousAgent
from core.config_loader import NexusConfig
import ollama
import yt_dlp
from urllib.parse import urlparse, parse_qs
import re

# 전역 인스턴스
core = ManagerCore()
hunter = ToolHunter()
autonomous_agent = AutonomousAgent(core)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 사용자가 PC에서 'ollama serve'를 실행한 상태라고 가정합니다.
    logger.info("🚀 Nexus Hub Server starting (Consolidated mode)...")
    logger.info(f"🔗 Worker LLM expected at: {NexusConfig.get_worker_url()}")
    
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
    component: str  # "core" or "worker"
    model: str

class YouTubeSummarizeRequest(BaseModel):
    url: str
    model_type: str = "local" # "local", "worker", "gemini"

class KnowledgeNoteRequest(BaseModel):
    content: str
    source_url: str = ""
    user_comment: str = ""
    category: str = "youtube"

class BulkDeleteRequest(BaseModel):
    ids: List[str]

# ==================== YouTube Extraction Utils ====================
def extract_video_id(url: str) -> str | None:
    parsed_url = urlparse(url)
    if parsed_url.hostname == 'youtu.be':
        return str(parsed_url.path)[1:]
    if parsed_url.hostname in ('www.youtube.com', 'youtube.com'):
        if parsed_url.path == '/watch':
            p = parse_qs(parsed_url.query)
            if 'v' in p: return p['v'][0]
        if parsed_url.path.startswith('/embed/'):
            return parsed_url.path.split('/')[2]
        if parsed_url.path.startswith('/v/'):
            return parsed_url.path.split('/')[2]
        if parsed_url.path.startswith('/shorts/'):
            return parsed_url.path.split('/')[2]
    return None

def get_yt_metadata(url: str):
    ydl_opts = {'quiet': True, 'skip_download': True, 'no_warnings': True, 'extract_flat': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "title": info.get('title', 'Unknown Title'),
                "author": info.get('uploader', info.get('channel', 'Unknown Author')),
                "thumbnail": info.get('thumbnail', ''),
                "description": info.get('description', ''),
            }
    except Exception as e:
        logger.warning(f"Metadata extraction failed: {e}")
        return {"title": "Unknown", "author": "Unknown", "thumbnail": "", "description": ""}

def get_yt_transcript(video_id: str):
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)
        transcript = transcript_list.find_transcript(['ko', 'en'])
        data = transcript.fetch()
        text = " ".join([getattr(d, 'text', d.get('text', '') if isinstance(d, dict) else '') for d in data])
        return {"text": text, "language": transcript.language_code, "method": "api"}
    except Exception as e:
        logger.error(f"YouTube API failed for {video_id}: {e}")
        return {"error": str(e)}

async def transcribe_audio_local(url: str):
    try:
        import whisper
        audio_file = f"temp_server_audio_{os.getpid()}"
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '128'}],
            'outtmpl': audio_file, 'quiet': True, 'no_warnings': True,
        }
        mp3_path = f"{audio_file}.mp3"
        await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))
        if not os.path.exists(mp3_path): return {"error": "Audio download failed"}
        result = await asyncio.to_thread(lambda: whisper.load_model("base").transcribe(mp3_path))
        if os.path.exists(mp3_path): os.remove(mp3_path)
        return {"text": result["text"], "language": result.get("language", "unknown"), "method": "whisper"}
    except Exception as e:
        logger.error(f"Whisper local error: {e}")
        return {"error": str(e)}

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
    """PC Ollama의 모델 목록 직접 조회 (/api/tags)"""
    worker_url = NexusConfig.get_worker_url()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            # Ollama의 모델 목록 엔드포인트는 /api/tags 입니다.
            async with session.get(f"{worker_url}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = data.get("models", [])
                    return [m.get("name") for m in models]
                return ["gemma2:9b (PC)"]
    except Exception as e:
        logger.error(f"Worker models lookup failed: {e}")
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
        
        # 주기가 변경되었으므로 자율 루프 재시작
        autonomous_agent.stop()
        autonomous_agent.start()
        
        return {"status": "success", "message": f"모니터링 주기가 {req.interval}초로 업데이트되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/research")
async def run_research(req: ResearchRequest):
    """서버에서 모든 도구를 직접 실행하는 연구 워크플로우 시작"""
    try:
        result = await manager.run(req.query)
        return result
    except Exception as e:
        logger.error(f"Research error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/learnings")
async def get_learnings():
    return {"status": "success", "learnings": memory.get_all_learnings()}

@app.post("/api/youtube/summarize")
async def youtube_summarize(req: YouTubeSummarizeRequest):
    """유튜브 요약 (분산 LLM 활용)"""
    try:
        video_id = extract_video_id(req.url)
        if not video_id: return {"status": "error", "message": "유효하지 않은 URL"}
        
        metadata = get_yt_metadata(req.url)
        result = get_yt_transcript(video_id)
        if "error" in result: result = await transcribe_audio_local(req.url)
        if "error" in result: return {"status": "error", "message": "자막 추출 실패"}
        
        transcript = result["text"]
        chunks = [transcript[i:i+4000] for i in range(0, len(transcript), 4000)]
        
        # 1. 고속 작업: Worker LLM을 사용하여 파편화된 요약/추출 수행
        extracted_facts = []
        for chunk in chunks:
            # use_remote=True (Worker)
            fact = await manager.llm.chat("너는 정보 추출가야. 핵심 내용만 요약해줘.", chunk, use_remote=(req.model_type=="worker"))
            extracted_facts.append(fact)
        
        combined_facts = "\n\n".join(extracted_facts)
        
        # 2. 깊은 추론: Manager LLM을 사용하여 최종 리포트 구성
        writer_system = "너는 유튜브 스크립트 요약 전문가야. 마크다운 구조로 한국어 요약해줘."
        writer_prompt = f"다음 내용을 바탕으로 요약해줘:\n{combined_facts}"
        
        final_summary = await manager.llm.chat(writer_system, writer_prompt, use_remote=False)
        
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
    return {
        "status": "online",
        "core_model": NexusConfig.get_model("core"),
        "worker_model": NexusConfig.get_model("worker"),
        "worker_url": NexusConfig.get_worker_url(),
        "mode": "consolidated"
    }

@app.get("/api/tools")
async def get_active_tools():
    manifest = NexusConfig.load_manifest()
    return manifest.get("tools", {})

@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        return await manager.run(req.query, req.user_id)
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
