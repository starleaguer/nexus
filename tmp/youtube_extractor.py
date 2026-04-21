import os
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import whisper

def get_video_id(url: str) -> str:
    from urllib.parse import urlparse, parse_qs
    parsed_url = urlparse(url)
    if parsed_url.hostname == 'youtu.be':
        return str(parsed_url.path)[1:]
    if parsed_url.hostname in ('www.youtube.com', 'youtube.com'):
        if parsed_url.path == '/watch':
            p = parse_qs(parsed_url.query)
            return p['v'][0]
        if parsed_url.path.startswith('/embed/'):
            return parsed_url.path.split('/')[2]
        if parsed_url.path.startswith('/v/'):
            return parsed_url.path.split('/')[2]
    return url

def get_metadata(url: str):
    print(f"Fetching metadata for {url}...")
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'no_warnings': True,
        'extract_flat': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            
            # Robust extraction of metadata
            return {
                "title": info_dict.get('title', 'Unknown Title'),
                "author": info_dict.get('uploader', info_dict.get('channel', 'Unknown Author')),
                "thumbnail": info_dict.get('thumbnail', ''),
                "description": info_dict.get('description', ''),
            }
    except Exception as e:
        print(f"Warning: Failed to extract metadata using yt-dlp: {e}")
        return {
            "title": "Unknown Title",
            "author": "Unknown Author",
            "thumbnail": "",
            "description": ""
        }

def get_transcript(video_id: str) -> str:
    print(f"Trying to get youtube transcript for {video_id}...")
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id).find_transcript(['ko', 'en'])
        transcript_data = transcript_list.fetch()
        text = " ".join([getattr(d, 'text', d.get('text', '') if isinstance(d, dict) else '') for d in transcript_data])
        print("Transcript fetched successfully via API.")
        print(text)
        return text
    except (TranscriptsDisabled, NoTranscriptFound, Exception) as e:
        print(f"Transcript fetch failed: {e}")
        return ""

def extract_audio_and_transcribe(url: str) -> str:
    print("Falling back to audio download + Whisper transcription...")
    audio_file = "temp_audio"
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': audio_file,
        'quiet': True,
        'no_warnings': True,
    }
    
    mp3_path = f"{audio_file}.mp3"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        print(f"Audio downloaded to {mp3_path}. Loading Whisper model...")
        # Note: can use 'base', 'small', or 'turbo' depending on performance.
        # 'turbo' or 'small' is fine for decent Korean. We will use 'small' or 'base'
        # The user has an M-series Mac likely if using Ollama, let's use 'small' for decent speed/quality.
        model = whisper.load_model("base")
        print("Transcribing with Whisper...")
        result = model.transcribe(mp3_path)
        
        print("Transcription complete.")
        return result["text"]
    except Exception as e:
        print(f"Error during audio extraction/transcription: {e}")
        return ""
    finally:
        if os.path.exists(mp3_path):
            os.remove(mp3_path)

def extract_youtube_content(url: str):
    video_id = get_video_id(url)
    metadata = get_metadata(url)
    
    # Try youtube-transcript-api first
    text = get_transcript(video_id)
    
    # Fallback to whisper
    if not text:
        text = extract_audio_and_transcribe(url)
        
    return {
        "video_id": video_id,
        "metadata": metadata,
        "transcript": text
    }
