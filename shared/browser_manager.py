import os
import json
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

class BrowserManager:
    """Playwright 기반 브라우저 및 세션 관리자"""
    
    def __init__(self):
        self.pw = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.session_file = Path("data/sessions/naver_session.json")
        os.makedirs(self.session_file.parent, exist_ok=True)

    async def start(self, headless: bool = True):
        """브라우저 엔진 시작"""
        if not self.pw:
            self.pw = await async_playwright().start()
        
        if not self.browser:
            self.browser = await self.pw.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"]
            )
        return self.browser

    async def get_context(self, use_session: bool = True, headless: bool = True) -> BrowserContext:
        """세션이 적용된 컨텍스트 반환"""
        await self.start(headless=headless)
        
        if self.context:
            return self.context

        # 세션 데이터 로드 시도
        cookies = []
        if use_session:
            cookies = self._load_cookies()
            
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        
        if cookies:
            await self.context.add_cookies(cookies)
            logger.info(f"✅ {len(cookies)}개의 쿠키가 세션에 주입되었습니다.")
            
        return self.context

    def _load_cookies(self) -> List[Dict]:
        """환경 변수 또는 파일에서 네이버 쿠키 로드"""
        cookies = []
        
        # 1. 환경 변수 확인 (NAVER_ 접두사 유무 모두 체크)
        nid_aut = os.getenv("NAVER_NID_AUT") or os.getenv("NID_AUT")
        nid_ses = os.getenv("NAVER_NID_SES") or os.getenv("NID_SES")
        
        if nid_aut and nid_ses:
            cookies.append({"name": "NID_AUT", "value": nid_aut, "domain": ".naver.com", "path": "/"})
            cookies.append({"name": "NID_SES", "value": nid_ses, "domain": ".naver.com", "path": "/"})
            logger.info("🔑 환경 변수에서 네이버 세션 쿠키를 로드했습니다.")
            return cookies

        # 2. 세션 파일 확인
        if self.session_file.exists():
            try:
                with open(self.session_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"세션 파일 로드 실패: {e}")
                
        return []

    async def save_session(self, context: BrowserContext):
        """현재 컨텍스트의 쿠키를 파일로 저장"""
        cookies = await context.cookies()
        with open(self.session_file, "w") as f:
            json.dump(cookies, f, indent=2)
        logger.info(f"💾 세션이 {self.session_file}에 저장되었습니다.")

    async def close(self):
        """브라우저 종료"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()
        self.context = None
        self.browser = None
        self.pw = None

async def get_naver_page(manager: BrowserManager, headless: bool = True) -> Page:
    """네이버에 로그인된 페이지 객체 반환"""
    context = await manager.get_context(headless=headless)
    page = await context.new_page()
    
    # 로그인 상태 확인 (네이버 메인 페이지 접속 후 닉네임 유무 또는 로그아웃 버튼 확인)
    await page.goto("https://www.naver.com")
    # 1. 프로필 영역 확인 2. '로그아웃' 텍스트 확인
    profile_area = await page.query_selector(".MyView-module__my_info___S_vFA, .nav_my")
    logout_text = await page.get_by_role("button", name="로그아웃").is_visible()
    
    is_logged_in = (profile_area is not None) or logout_text
    
    if not is_logged_in:
        logger.warning("⚠️ 네이버 세션이 만료되었거나 로그인되어 있지 않습니다. (.env의 NID_AUT, NID_SES 확인 필요)")
    else:
        logger.info("✅ 네이버 로그인 상태 확인됨.")
        
    return page
