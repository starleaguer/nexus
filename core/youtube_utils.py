import os
import logging
import asyncio
import yt_dlp
from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

logger = logging.getLogger(__name__)

def extract_video_id(url: str) -> Optional[str]:
    """유튜브 URL에서 영상 ID를 추출합니다."""
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

def get_yt_metadata(url: str) -> Dict[str, Any]:
    """영상 메타데이터(제목, 작성자, 썸네일 등)를 가져옵니다."""
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

def get_yt_transcript(video_id: str) -> Dict[str, Any]:
    """공식 API를 통해 유튜브 자막을 가져옵니다."""
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        try:
            transcript = transcript_list.find_transcript(['ko', 'en'])
        except NoTranscriptFound:
            transcript = transcript_list.find_generated_transcript(['ko', 'en'])
            
        data = transcript.fetch()
        text = " ".join([t.text if hasattr(t, 'text') else t.get('text', '') for t in data])
        return {"text": text, "language": transcript.language_code, "method": "api"}
    except Exception as e:
        logger.error(f"YouTube API failed for {video_id}: {e}")
        return {"error": str(e)}

async def transcribe_audio_whisper(url: str) -> Dict[str, Any]:
    """Whisper를 사용하여 음성을 텍스트로 변환합니다. (Fallback용)"""
    try:
        import whisper
        audio_file = f"temp_audio_{os.getpid()}"
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '128'}],
            'outtmpl': audio_file, 'quiet': True, 'no_warnings': True,
        }
        mp3_path = f"{audio_file}.mp3"
        
        # 오디오 다운로드 (비동기 처리)
        await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))
        
        if not os.path.exists(mp3_path):
            return {"error": "Audio download failed"}
            
        # Whisper 변환 (비동기 처리)
        result = await asyncio.to_thread(lambda: whisper.load_model("base").transcribe(mp3_path))
        
        if os.path.exists(mp3_path):
            os.remove(mp3_path)
            
        return {
            "text": result["text"],
            "language": result.get("language", "unknown"),
            "method": "whisper"
        }
    except Exception as e:
        logger.error(f"Whisper transcription error: {e}")
        return {"error": str(e)}
async def summarize_video(url: str, orchestrator: Any, model_type: str = "auto") -> Dict[str, Any]:
    """
    유튜브 영상의 자막을 추출하고, 3단계(추출 -> 요약 -> 인사이트) 프로세스를 통해 분석 리포트를 생성합니다.
    분산 LLM 및 자동 모델 라우팅(Tier 1/3)을 지원합니다.
    """
    from core.model_selector import ModelAvailabilityService
    
    video_id = extract_video_id(url)
    if not video_id: return {"status": "error", "message": "유효하지 않은 유튜브 URL입니다."}
    
    metadata = get_yt_metadata(url)
    result = get_yt_transcript(video_id)
    
    if "error" in result:
        result = await transcribe_audio_whisper(url)
    if "error" in result:
        return {"status": "error", "message": f"자막 추출 실패: {result.get('error')}"}
    
    transcript = result["text"]
    svc = ModelAvailabilityService()
    
    # ── 모델 라우팅 결정 ─────────────────────────
    use_remote, llm_model = False, None
    if model_type == "worker":
        use_remote, llm_model = True, None
    elif model_type == "local":
        use_remote, llm_model = False, None

    chunks = [transcript[i:i+4000] for i in range(0, len(transcript), 4000)]
    logger.info(f"📦 [YouTube] 총 {len(chunks)}개 청크 분할 완료")

    # 1단계: 청크별 핵심 내용 추출 (부하 분산 적용)
    extracted_facts = []
    for i, chunk in enumerate(chunks):
        current_model, current_remote = llm_model, use_remote
        if model_type in ("auto", "gemini"):
            best = await svc.get_best_available_model("fast")
            current_model = best["model"]
            current_remote = (best["provider"] == "worker")
            if i == 0 or i % 5 == 0:
                logger.info(f"🔄 [Chunk {i+1}/{len(chunks)}] Routing: {current_model} ({best['provider']})")

        fact = await orchestrator.llm.chat(
            "너는 정보 추출가야. 핵심 내용만 bullet point로 한국어로 요약해줘.",
            chunk,
            use_remote=current_remote,
            model=current_model
        )
        extracted_facts.append(fact)
    combined_facts = "\n\n".join(extracted_facts)

    # 2단계: 최종 마크다운 요약 생성 (Tier 1 우선)
    summary_model, summary_remote = current_model, current_remote
    if model_type == "auto":
        best_summary = await svc.get_best_available_model("bulk")
        summary_model = best_summary["model"]
        summary_remote = (best_summary["provider"] == "worker")
        logger.info(f"📝 [YouTube Step2] Organizing with Tier{best_summary['tier']} ({summary_model})")

    final_summary = await orchestrator.llm.chat(
        "너는 유튜브 스크립트 요약 전문가야. 마크다운 구조로 체계적인 한국어 요약 리포트를 작성해줘.",
        f"다음 내용을 바탕으로 요약해줘:\n{combined_facts}",
        use_remote=summary_remote,
        model=summary_model
    )

    # 3단계: 이면(Hidden Insight) 추론 (Tier 3 우선)
    if model_type == "auto":
        insight_best = await svc.get_best_available_model("deep")
        insight_model = insight_best["model"]
        insight_remote = (insight_best["provider"] == "worker")
        logger.info(f"🔬 [YouTube Step3] Inferring with Tier{insight_best['tier']} ({insight_model})")
    else:
        insight_model, insight_remote = llm_model, use_remote

    insight = await orchestrator.llm.chat(
        """너는 심층 미디어 분석 전문가야.
영상 요약을 읽고, 겉으로 드러나지 않는 숨겨진 이면, 화자의 진짜 의도, 생략된 맥락, 편향 가능성, 시청자에게 미칠 심리적 영향을 비판적으로 추론해줘.
마크다운 형식으로 한국어로 작성하되, 다음 항목을 포함해줘:
1. 🎯 화자의 핵심 메시지와 숨겨진 의도
2. 🔍 드러나지 않은 전제 / 생략된 맥락
3. ⚠️ 편향 또는 프레이밍 주의점
4. 💡 시청자가 알아야 할 숨겨진 인사이트""",
        f"[요약 내용]\n{final_summary}",
        use_remote=insight_remote,
        model=insight_model
    )
    
    return {
        "status": "success",
        "video_id": video_id,
        "title": metadata.get("title", ""),
        "language": result.get("language", ""),
        "metadata": metadata,
        "summary": final_summary,
        "insight": insight
    }

async def get_yt_transcript_with_fallback(video_id: str, url: str) -> Dict[str, Any]:
    """공식 API를 우선 시도하고, 실패 시 Whisper를 사용하여 자막을 추출합니다."""
    # 1. API 시도
    result = get_yt_transcript(video_id)
    
    # 2. 실패 시 Whisper 시도
    if "error" in result:
        logger.info(f"🔄 YouTube API failed, falling back to Whisper for {video_id}")
        result = await transcribe_audio_whisper(url)
        
    return result
