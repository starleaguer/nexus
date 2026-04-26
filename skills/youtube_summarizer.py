"""
YouTube Summarizer Skill (Enhanced)
유튜브 영상의 메타데이터를 추출하고 자막 또는 음성 인식을 통해 텍스트를 반환합니다.
Reference: tmp/youtube_extractor.py
"""
import os
import re
import logging
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

def extract_video_id(url: str) -> str | None:
    """유튜브 URL에서 영상 ID를 정밀하게 추출합니다."""
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

def get_metadata(url: str):
    """yt-dlp를 사용하여 영상의 제목, 작성자, 썸네일 등을 가져옵니다."""
    logger.info(f"Fetching metadata for {url}...")
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'no_warnings': True,
        'extract_flat': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            return {
                "title": info_dict.get('title', 'Unknown Title'),
                "author": info_dict.get('uploader', info_dict.get('channel', 'Unknown Author')),
                "thumbnail": info_dict.get('thumbnail', ''),
                "description": info_dict.get('description', ''),
            }
    except Exception as e:
        logger.warning(f"Failed to extract metadata: {e}")
        return {
            "title": "Unknown Title",
            "author": "Unknown Author",
            "thumbnail": "",
            "description": ""
        }

def get_transcript_via_api(video_id: str, max_chars: int = 10000) -> dict:
    """YouTubeTranscriptApi를 사용하여 자막을 가져옵니다."""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        # 한국어 우선 시도
        try:
            transcript = transcript_list.find_transcript(['ko'])
        except NoTranscriptFound:
            try:
                transcript = transcript_list.find_transcript(['en'])
            except NoTranscriptFound:
                # 자동 생성 자막 시도
                transcript = transcript_list.find_generated_transcript(['ko', 'en'])
        
        data = transcript.fetch()
        full_text = " ".join([t["text"] for t in data])
        return {"text": full_text[:max_chars], "language": transcript.language_code, "method": "api"}
    except (TranscriptsDisabled, NoTranscriptFound, Exception) as e:
        logger.warning(f"API transcript fetch failed: {e}")
        return {"error": str(e)}

def extract_audio_and_transcribe(url: str, max_chars: int = 10000) -> dict:
    """Whisper를 사용하여 음성을 텍스트로 변환합니다. (Fallback)"""
    logger.info("Falling back to Whisper transcription...")
    import whisper
    
    audio_file = f"temp_audio_{os.getpid()}"
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
        'outtmpl': audio_file,
        'quiet': True,
        'no_warnings': True,
    }
    
    mp3_path = f"{audio_file}.mp3"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        if not os.path.exists(mp3_path):
            return {"error": "Audio file not created"}

        logger.info(f"Loading Whisper model (base)...")
        model = whisper.load_model("base")
        logger.info("Transcribing...")
        result = model.transcribe(mp3_path)
        
        return {
            "text": result["text"][:max_chars],
            "language": result.get("language", "unknown"),
            "method": "whisper"
        }
    except Exception as e:
        logger.error(f"Whisper transcription error: {e}")
        return {"error": f"Whisper error: {str(e)}"}
    finally:
        if os.path.exists(mp3_path):
            try: os.remove(mp3_path)
            except: pass

def run(params: dict) -> dict:
    """
    워커 API 진입점.
    """
    url = params.get("url", "")
    if not url:
        return {"error": "URL이 제공되지 않았습니다."}

    video_id = extract_video_id(url)
    if not video_id:
        return {"error": "유효한 유튜브 URL이 아닙니다."}

    metadata = get_metadata(url)
    
    # 1. API 시도
    result = get_transcript_via_api(video_id)
    
    # 2. 실패 시 Whisper 시도
    if "error" in result:
        result = extract_audio_and_transcribe(url)
    
    if "error" in result:
        return {"error": f"내용 추출 실패: {result['error']}", "metadata": metadata}

    return {
        "video_id": video_id,
        "url": url,
        "metadata": metadata,
        "transcript": result["text"],
        "language": result["language"],
        "method": result["method"],
        "char_count": len(result["text"])
    }
