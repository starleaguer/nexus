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
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            transcript = transcript_list.find_transcript(['ko', 'en'])
        except NoTranscriptFound:
            transcript = transcript_list.find_generated_transcript(['ko', 'en'])
            
        data = transcript.fetch()
        text = " ".join([t.get('text', '') for t in data])
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
