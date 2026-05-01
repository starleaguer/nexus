"""
유튜브 영상 분석 및 텍스트 요약 스킬.
[사용 시점] 유튜브 영상의 메타데이터나 자막 텍스트, 핵심 요약 내용이 필요할 때 사용.
[출력] 영상 제목, 조회수, 자막 원본 및 AI 기반 핵심 요약 데이터.
"""
import logging
from typing import Dict, Any
import core.youtube_utils as yt_utils

logger = logging.getLogger(__name__)

async def run_async(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    유튜브 영상 분석 스킬.
    - summarize=True일 경우: 3단계 심층 요약 리포트 생성
    - 기본값: 자막 및 메타데이터 추출
    """
    url = params.get("url", "")
    if not url:
        return {"error": "URL이 제공되지 않았습니다."}

    # 프로젝트 오케스트레이터 가져오기 (이미 메인에서 실행 중이므로 import만)
    from main import core
    
    # 요약 요청 여부 확인
    do_summarize = params.get("summarize", False) or "요약" in params.get("query", "")
    
    if do_summarize:
        logger.info(f"📝 [YouTube Skill] 심층 요약 모드 시작: {url}")
        return await yt_utils.summarize_video(url, orchestrator=core, model_type=params.get("model_type", "auto"))

    # 기본 동작: 자막 추출
    video_id = yt_utils.extract_video_id(url)
    if not video_id: return {"error": "유효한 유튜브 URL이 아닙니다."}

    metadata = yt_utils.get_yt_metadata(url)
    result = await yt_utils.get_yt_transcript_with_fallback(video_id, url) # 기존 로직 추상화 가정
    
    if "error" in result:
        return {"error": f"내용 추출 실패: {result['error']}", "metadata": metadata}

    transcript = result["text"]
    return {
        "status": "success",
        "video_id": video_id,
        "metadata": metadata,
        "transcript": transcript[:10000], # 스킬로 반환 시에는 일정 길이 제한
        "method": result.get("method", "api")
    }

def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """유튜브 영상 분석 및 자동 요약 도구.
    [사용 시점] 
    - 유튜브 영상의 메타데이터(제목, 조회수 등)나 자막 내용이 필요할 때
    - 영상 전체 내용을 AI가 분석한 핵심 요약 리포트로 받고 싶을 때
    
    [파라미터]
    - url: 유튜브 영상 URL (필수, 예: "https://www.youtube.com/watch?v=...")
    - summarize: true 설정 시 AI 심층 요약 리포트 생성 (선택)
    
    [출력] 
    영상 정보, 자막 텍스트 또는 3단계 심층 요약 리포트 반환
    """
    import asyncio
    # 별도 스레드에서 실행되므로 안전하게 asyncio.run 사용
    return asyncio.run(run_async(params))
