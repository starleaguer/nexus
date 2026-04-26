"""
YouTube Summarizer Skill (Enhanced)
유튜브 영상의 메타데이터를 추출하고 자막 또는 음성 인식을 통해 텍스트를 반환합니다.
"""
import logging
from typing import Dict, Any
import core.youtube_utils as yt_utils

logger = logging.getLogger(__name__)

async def run_async(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    비동기 실행 로직
    """
    url = params.get("url", "")
    if not url:
        return {"error": "URL이 제공되지 않았습니다."}

    video_id = yt_utils.extract_video_id(url)
    if not video_id:
        return {"error": "유효한 유튜브 URL이 아닙니다."}

    metadata = yt_utils.get_yt_metadata(url)
    
    # 1. API 시도
    result = yt_utils.get_yt_transcript(video_id)
    
    # 2. 실패 시 Whisper 시도
    if "error" in result:
        result = await yt_utils.transcribe_audio_whisper(url)
    
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

def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    워커 API 진입점 (동기 래퍼)
    """
    import asyncio
    try:
        # 이미 루프가 실행 중인 경우를 대비해 처리
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 새로운 스레드에서 실행하거나 동기적으로 변환 필요
            # 여기서는 단순화를 위해 직접 실행 (ManagerCore에서 비동기로 호출하는 것이 좋음)
            return loop.run_until_complete(run_async(params))
        else:
            return asyncio.run(run_async(params))
    except Exception as e:
        # 대안: 새로운 루프 생성
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        return new_loop.run_until_complete(run_async(params))
