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

from manager.manager_core import ManagerCore
from manager.researcher import ToolHunter
# AutonomousAgent import removed (moved to worker)
from shared.config_loader import NexusConfig
import ollama
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from urllib.parse import urlparse, parse_qs
import re

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
    model_type: str = "local" # "local" or "gemini"

class KnowledgeNoteRequest(BaseModel):
    content: str
    source_url: str = ""
    user_comment: str = ""
    category: str = "youtube"

class BulkDeleteRequest(BaseModel):
    ids: List[str]

# ==================== YouTube Extraction Utils (Local) ====================
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
    logger.info(f"Trying to get transcript for video_id: {video_id}...")
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        # tmp/youtube_extractor.py 방식: 객체 속성 접근이 필요함
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)
        transcript = transcript_list.find_transcript(['ko', 'en'])
        
        data = transcript.fetch()
        # FetchedTranscriptSnippet 객체 또는 dict 모두 지원하도록 getattr 사용
        text = " ".join([getattr(d, 'text', d.get('text', '') if isinstance(d, dict) else '') for d in data])
        
        logger.info(f"Transcript fetched successfully (Method: API, Lang: {transcript.language_code})")
        return {"text": text, "language": transcript.language_code, "method": "api"}
            
    except Exception as e:
        logger.error(f"YouTube API failed for {video_id}: {type(e).__name__} - {str(e)}")
        return {"error": str(e)}

async def transcribe_audio_local(url: str):
    """Whisper를 사용하여 로컬에서 음성 인식 (Fallback)"""
    try:
        import whisper
        audio_file = f"temp_server_audio_{os.getpid()}"
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '128'}],
            'outtmpl': audio_file, 'quiet': True, 'no_warnings': True,
        }
        mp3_path = f"{audio_file}.mp3"
        
        # 다운로드는 블로킹 작업이므로 스레드에서 실행
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        
        await asyncio.to_thread(download)
        
        if not os.path.exists(mp3_path):
            return {"error": "Audio download failed"}
            
        # Whisper 로드 및 변환도 블로킹이므로 스레드에서 실행
        def run_whisper():
            model = whisper.load_model("base")
            return model.transcribe(mp3_path)
            
        result = await asyncio.to_thread(run_whisper)
        
        if os.path.exists(mp3_path):
            os.remove(mp3_path)
            
        return {"text": result["text"], "language": result.get("language", "unknown"), "method": "whisper"}
    except Exception as e:
        logger.error(f"Whisper local error: {e}")
        return {"error": str(e)}

# ==================== 엔드포인트 ====================

@app.get("/api/models/manager")
async def get_manager_models():
    """Get Ollama model list from the local server (Manager)"""
    try:
        logger.info("🔍 Fetching local Ollama models for Manager...")
        # ollama.list() returns the model information
        resp = ollama.list()
        
        # 리스트 또는 객체 응답 처리
        if hasattr(resp, 'models'):
            models_data = resp.models
        elif isinstance(resp, dict):
            models_data = resp.get("models", [])
        else:
            models_data = resp # Fallback for unexpected formats
            
        model_names = []
        for m in models_data:
            if isinstance(m, dict):
                model_names.append(m.get("model"))
            elif hasattr(m, 'model'):
                model_names.append(m.model)
            else:
                model_names.append(str(m))
        
        logger.info(f"✅ Found {len(model_names)} local models: {model_names}")
        return model_names
    except Exception as e:
        logger.error(f"❌ Local Ollama models check failed: {e}")
        # 기본값 제공 (Ollama가 꺼져있을 경우 등)
        return ["gemma2:27b", "gemma2:9b", "gemma4:latest"]

@app.get("/api/models/worker")
@app.get("/api/models") # 하위 호환성을 위해 유지
async def get_worker_models():
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
            logger.error(f"Failed to proxy worker models request: {e}")
            raise HTTPException(status_code=500, detail="Unable to retrieve models from worker")

@app.post("/api/config/model")
async def update_model_config(req: ModelConfigRequest):
    """시스템 모델 설정 업데이트 (proxy worker component)"""
    try:
        # Proxy updates for worker component
        if req.component == "worker":
            worker_url = NexusConfig.get_worker_url()
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.post(f"{worker_url}/api/config/model", json=req.model_dump()) as resp:
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

@app.post("/api/learnings/delete-bulk")
async def delete_learnings_bulk(req: BulkDeleteRequest):
    """학습 로그 대량 삭제"""
    try:
        success = memory.delete_learnings(req.ids)
        if success:
            return {"status": "success", "message": f"{len(req.ids)}건의 학습 로그가 삭제되었습니다."}
        else:
            raise HTTPException(status_code=500, detail="삭제 중 오류가 발생했습니다.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/youtube/summarize")
async def youtube_summarize(req: YouTubeSummarizeRequest):
    """유튜브 URL 추출부터 요약까지 MacBook(Manager)에서 온전히 처리"""
    try:
        from manager.manager_core import OllamaClient
        
        # 1. 정보 추출 (Local)
        logger.info(f"📹 YouTube 요약 요청 (Server-Side): {req.url}")
        video_id = extract_video_id(req.url)
        if not video_id:
            return {"status": "error", "message": "유효하지 않은 YouTube URL입니다."}
            
        metadata = get_yt_metadata(req.url)
        
        # 2. 자막 추출 (API -> Whisper Fallback)
        result = get_yt_transcript(video_id)
        if "error" in result:
            logger.info("API 자막 실패, Whisper 로컬 변환 시도...")
            result = await transcribe_audio_local(req.url)
            
        if "error" in result:
            return {"status": "error", "message": f"내용 추출 실패: {result['error']}"}
            
        transcript = result["text"]
        language = result.get("language", "unknown")

        # 3. 요약 파이프라인 (Local)
        def chunk_text(text, size=4000):
            return [text[i:i+size] for i in range(0, len(text), size)]
            
        chunks = chunk_text(transcript)
        logger.info(f"Transcript length: {len(transcript)}, chunks: {len(chunks)}")

        if req.model_type == "gemini":
            try:
                from google import genai
                api_key = os.getenv("GOOGLE_API_KEY")
                if not api_key:
                    raise Exception("GOOGLE_API_KEY가 없습니다.")
                client = genai.Client(api_key=api_key)
                
                def chat_func(system, user):
                    prompt = f"{system}\n\n[내용]\n{user}"
                    response = client.models.generate_content(
                        model="gemini-3.1-flash-lite-preview",
                        contents=prompt
                    )
                    return response.text
                logger.info("✨ Using New Gemini SDK (gemini-3.1-flash-lite-preview)")
            except Exception as e:
                logger.error(f"Gemini error: {e}, fallback to local")
                llm = OllamaClient()
                chat_func = llm.chat
        elif req.model_type == "worker":
            # Worker의 Ollama 사용
            worker_url = NexusConfig.get_worker_url().replace(":8000", ":11434") # Ollama 기본 포트 시도
            worker_model = NexusConfig.get_model("worker")
            logger.info(f"👷 Using Worker LLM ({worker_model}) at {worker_url}")
            
            from ollama import Client
            worker_client = Client(host=worker_url)
            
            def chat_func(system, user):
                resp = worker_client.chat(
                    model=worker_model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user}
                    ]
                )
                return resp['message']['content']
        else:
            llm = OllamaClient()
            chat_func = llm.chat
            logger.info("🏠 Using Local model (Manager)")

        # Agent Pipeline
        extracted_facts = []
        for i, chunk in enumerate(chunks):
            fact = chat_func("너는 정보 추출가야. 핵심 내용만 요약해줘.", chunk)
            extracted_facts.append(fact)
            
        combined_facts = "\n\n".join(extracted_facts)
        
        # tmp/summarizer.py의 구조화된 프롬프트 적용
        writer_system = "너는 유튜브 스크립트 요약 전문가야. 반드시 한국어로, 아래의 일관된 마크다운 구조를 엄격하게 지켜서 요약해줘."
        writer_prompt = f"""다음 추출된 데이터들을 바탕으로 아래 구조에 맞춰서 요약해줘.
---
### 📌 1. 핵심 요약 (Overview)
- 영상의 주제와 가장 중요한 결론을 2~3문장 이내로 직관적으로 요약하세요.

### 🔑 2. 주요 포인트 (Key Points)
- 영상의 핵심 내용 3~5가지를 글머리 기호(`-`)로 정리하세요.
- 각 포인트의 제목은 **굵은 글씨**로 강조하고, 간단한 부연 설명을 덧붙이세요.

### 📜 3. 세부 내용 (Detailed Summary)
- 영상의 구조와 화자의 의도를 반영해서 마치 직접 본 것처럼 요약해줘.
- 중요한 키워드나 개념은 `단어` 또는 **단어** 형태로 강조하세요.

### 💡 4. 인사이트 (Insights / Takeaways)
- 이 영상에서 얻을 수 있는 교훈, 실무 적용 방안, 또는 새롭게 알게 된 통찰을 1~2가지 작성하세요.
---
[추출된 팩트 데이터]
{combined_facts}"""

        final_summary = chat_func(writer_system, writer_prompt)
        
        return {
            "status": "success",
            "video_id": video_id,
            "url": req.url,
            "metadata": metadata,
            "language": language,
            "summary": final_summary
        }
    except Exception as e:
        logger.error(f"YouTube summarize error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
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

@app.post("/api/autonomous/logs/delete-bulk")
async def delete_autonomous_logs_bulk(req: BulkDeleteRequest):
    """자율 로그 대량 삭제"""
    try:
        success = memory.delete_autonomous_logs(req.ids)
        if success:
            return {"status": "success", "message": f"{len(req.ids)}건의 자율 로그가 삭제되었습니다."}
        else:
            raise HTTPException(status_code=500, detail="삭제 중 오류가 발생했습니다.")
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
