"""
네이버 카페 게시글 읽기, 검색 및 테마주 분석 도구.
[사용 시점] 네이버 카페의 게시글 내용을 읽거나, 키워드 검색, 또는 국내 테마주(핵심뉴스, 오늘의 테마) 분석이 필요할 때 사용.
[출력] 게시글 정보, 검색 결과 또는 테마별 그룹화된 분석 데이터. 
[액션] read(게시글 읽기), board(게시판 목록), search(검색), list(카페 목록), theme_analysis(테마주 종합 분석).
"""
import logging
import asyncio
import re
import os
import datetime
from typing import Dict, Any, List, Optional
from shared.browser_manager import BrowserManager, get_naver_page
from core.config_loader import NexusConfig

logger = logging.getLogger(__name__)

class NaverCafeSkill:
    """네이버 카페 게시글 읽기 및 검색 스킬"""

    def __init__(self):
        self.browser_manager = BrowserManager()

    async def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """워커 실행 엔트리포인트"""
        action = params.get("action", "read")
        # 방어적 코딩: LLM이 흔히 사용하는 'analyze'를 'theme_analysis'로 매핑
        if action == "analyze":
            action = "theme_analysis"
            
        cafe_id = params.get("cafe_id")  # 카페 고유 ID 또는 URL명
        article_id = params.get("article_id")
        query = params.get("query")
        filter_today = params.get("filter_today", False)
        analyze_vision = params.get("analyze_vision", False)
        
        try:
            if action == "read":
                if not cafe_id or not article_id:
                    # URL에서 추출 시도
                    url = params.get("url", "")
                    if "cafe.naver.com" in url:
                        m = re.search(r"cafe.naver.com/([^/]+)/(\d+)", url)
                        if m:
                            cafe_id, article_id = m.groups()
                
                if not cafe_id or not article_id:
                    return {"status": "error", "message": "cafe_id와 article_id가 필요합니다."}
                return await self.read_post(cafe_id, article_id, analyze_vision=analyze_vision)
            
            elif action == "theme_analysis":
                return await self.analyze_theme_stocks()
            
            elif action == "search":
                if not cafe_id or not query:
                    return {"status": "error", "message": "cafe_id와 query가 필요합니다."}
                return await self.search_posts(cafe_id, query)
            
            elif action == "board":
                url = params.get("url")
                if not url:
                    return {"status": "error", "message": "게시판 URL이 필요합니다."}
                return await self.get_board_posts(url, filter_today=filter_today)
            
            elif action == "list":
                return await self.list_my_cafes()
                
            return {"status": "error", "message": f"지원하지 않는 액션: {action}"}
            
        except Exception as e:
            logger.error(f"NaverCafeSkill 실행 오류: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            await self.browser_manager.close()

    async def read_post(self, cafe_id: str, article_id: str, analyze_vision: bool = False) -> Dict[str, Any]:
        """특정 게시글의 제목, 본문, 댓글을 추출"""
        page = await get_naver_page(self.browser_manager, headless=False)
        
        # cafe_id가 숫자인 경우와 문자열인 경우 구분
        if cafe_id.isdigit():
            url = f"https://cafe.naver.com/f-e/cafes/{cafe_id}/articles/{article_id}"
        else:
            url = f"https://cafe.naver.com/{cafe_id}/{article_id}"
            
        logger.info(f"📖 게시글 읽기: {url}")
        await page.goto(url)
        
        # iframe 전환
        try:
            await page.wait_for_selector("#cafe_main", timeout=10000)
        except:
            logger.warning("cafe_main 아이프레임을 찾을 수 없습니다.")
            
        frame = page.frame(name="cafe_main")
        if not frame:
            return {"status": "error", "message": "게시글 프레임을 찾을 수 없습니다."}

        logger.debug(f" 현재 프레임 URL: {frame.url}")
        
        # 데이터 추출 (선택자 대응)
        try:
            # 콘텐츠가 로드될 때까지 대기
            await frame.wait_for_selector(".title_text, .se-main-container, .article_viewer", timeout=10000)
            title = await frame.inner_text(".title_text")
            author = await frame.inner_text(".nickname")
            content_el = await frame.query_selector(".article_viewer")
            content = await content_el.inner_text() if content_el else ""
            
            # 이미지 정보 추출 및 캡처
            images = []
            image_paths = []
            img_els = await frame.query_selector_all(".article_viewer img, .se-image img, .se-main-container img, .se-image-resource img, img[src*='postfiles']")
            logger.debug(f" 발견된 이미지 요소 수: {len(img_els)}")
            
            for i, img in enumerate(img_els):
                src = await img.get_attribute("src")
                logger.debug(f" 이미지 {i} src: {src}")
                if src and not src.startswith("data:"):
                    images.append(src)
                    
                    if analyze_vision:
                        # 이미지 스크린샷 캡처
                        img_path = f"data/images/cafe_{article_id}_{i}.png"
                        os.makedirs("data/images", exist_ok=True)
                        try:
                            # 이미지가 보이도록 스크롤 및 로딩 대기
                            await img.scroll_into_view_if_needed()
                            # 이미지가 로드될 때까지 대기 (naturalWidth 확인)
                            await page.wait_for_function(
                                "el => el.naturalWidth > 0", 
                                arg=img, 
                                timeout=10000
                            )
                            await asyncio.sleep(1) 
                            await img.screenshot(path=img_path)
                            image_paths.append(img_path)
                            logger.debug(f" ✅ 이미지 캡처 성공: {img_path}")
                        except Exception as e:
                            logger.debug(f" ❌ 이미지 캡처 실패 ({src}): {e}")
            
            # 댓글 추출
            comments = []
            comment_els = await frame.query_selector_all(".comment_list .comment_item")
            for item in comment_els:
                author_el = await item.query_selector(".nickname")
                text_el = await item.query_selector(".comment_text")
                if author_el and text_el:
                    comments.append({
                        "author": await author_el.inner_text(),
                        "text": await text_el.inner_text()
                    })
            # 링크 추출 (<a> 태그 href 우선)
            links = []
            link_els = await frame.query_selector_all(".article_viewer a, .se-main-container a")
            for link_el in link_els:
                href = await link_el.get_attribute("href")
                if href and href.startswith("http"):
                    links.append(href)
            
            # 중복 제거
            links = list(dict.fromkeys(links))
            
            return {
                "status": "success",
                "data": {
                    "title": title.strip(),
                    "author": author.strip(),
                    "content": content.strip(),
                    "links": links, # 새로 추가
                    "images": images,
                    "image_paths": image_paths,
                    "comments": comments,
                    "url": url
                }
            }
        except Exception as e:
            return {"status": "error", "message": f"데이터 추출 실패: {str(e)}"}

    async def search_posts(self, cafe_id: str, query: str) -> Dict[str, Any]:
        """카페 내 게시글 검색"""
        page = await get_naver_page(self.browser_manager)
        # 검색 URL 구성
        search_url = f"https://cafe.naver.com/ArticleSearchList.nhn?search.clubid={cafe_id}&search.searchBy=0&search.query={query}"
        # 주의: cafe_id가 숫자인 경우와 문자열인 경우가 다를 수 있음. 
        # 여기서는 문자열(URL명) 기반으로 접근하는 것이 일반적이나, 공식 API가 아니므로 확인 필요.
        
        # 실제로는 카페 메인 접속 후 검색창 이용하는 것이 더 정확함
        await page.goto(f"https://cafe.naver.com/{cafe_id}")
        frame = page.frame(name="cafe_main")
        if not frame:
            return {"status": "error", "message": "카페 메인 접속 실패"}
            
        await frame.fill("#topLayerQueryInput", query)
        await frame.click(".btn-search-upper")
        await asyncio.sleep(2) # 검색 로딩 대기
        
        # 결과 목록 추출
        posts = []
        post_elements = await frame.query_selector_all(".article-board .article")
        for el in post_elements[:5]: # 상위 5개만
            title = await el.inner_text()
            link = await el.get_attribute("href")
            posts.append({"title": title.strip(), "link": link})
            
        return {"status": "success", "posts": posts}

    async def get_board_posts(self, url: str, filter_today: bool = False) -> Dict[str, Any]:
        """특정 게시판 URL에서 게시글 목록을 추출"""
        if "/ca-fe/" in url:
            url = url.replace("/ca-fe/", "/f-e/")
            logger.info(f"🔄 URL 경로 변환: ca-fe -> f-e ({url})")

        page = await get_naver_page(self.browser_manager, headless=False)
        logger.info(f"📋 게시판 목록 조회: {url} (오늘 글만: {filter_today})")
        
        await page.goto(url, wait_until="networkidle", timeout=30000)
        
        # iframe(cafe_main)이 있는지 확인 (구버전 UI)
        target = page
        frame = page.frame(name="cafe_main")
        if frame:
            target = frame
            logger.info("📦 게시판이 아이프레임(cafe_main) 내에 있습니다.")
        else:
            logger.info("📦 게시판이 메인 문서(현대적 UI)에 있습니다.")
            
        try:
            # 게시글 요소가 나타날 때까지 대기
            await target.wait_for_selector(".article-board tr, .ArticleItem, a.article, [class*='ArticleListItem_item']", timeout=15000)
            await asyncio.sleep(2)
        except:
            await page.wait_for_load_state("networkidle", timeout=5000)
            
        posts = []
        try:
            # 1. 다양한 형태의 아이템 탐색 (테이블 tr, 현대적 div 리스트 등)
            items = await target.query_selector_all(".article-board tr, tr, [class*='ArticleListItem_item'], .ArticleItem")
            logger.debug(f" 발견된 아이템 수: {len(items)}")

            for item in items:
                tag = await item.evaluate("el => el.tagName")
                cls = await item.get_attribute("class") or ""
                
                # 클래스명을 통한 공지/인기글 제외
                if any(k in cls.lower() for k in ["notice", "best", "announce"]):
                    continue

                # 번호/유형 열 탐색
                number_el = await item.query_selector(".td_article, .number, .inner_number, .badge_notice, [class*='ArticleListItem_number'], td:first-child")
                if number_el:
                    num_text = (await number_el.inner_text()).strip()
                    # 숫자가 아니고 '공지', '필독' 등이 포함되면 스킵
                    if num_text and not num_text.isdigit() and any(k in num_text for k in ["공지", "필독", "인기"]):
                        continue
                
                # 제목 및 링크 추출
                title_el = await item.query_selector("a.article, .article_title, .td_article, [class*='ArticleListItem_title'], .inner_list a, .board-list a")
                if not title_el:
                    # td 내부의 a 태그 탐색
                    title_el = await item.query_selector("td a.article, td a")
                
                if not title_el: continue
                    
                title = (await title_el.inner_text()).strip()
                link = await title_el.get_attribute("href")
                
                if not title or not link: continue

                # 날짜 추출
                date_el = await item.query_selector(".type_date, .td_date, .date, .time, [class*='ArticleListItem_date'], td:nth-last-child(2)")
                date_text = (await date_el.inner_text()).strip() if date_el else ""
                
                logger.debug(f" [FOUND] Title: {title[:20]} | Date: {date_text}")
                
                if not date_text:
                    item_text = await item.inner_text()
                    time_match = re.search(r'\d{1,2}:\d{2}', item_text)
                    date_match = re.search(r'\d{4}\.\d{2}\.\d{2}\.?', item_text)
                    date_text = time_match.group() if time_match else (date_match.group() if date_match else "unknown")
                    
                if title.strip() and link:
                    if link.startswith("/"):
                        link = f"https://cafe.naver.com{link}"
                    
                    # 오늘 날짜 판별 (HH:mm 형식)
                    is_today = ":" in date_text and "." not in date_text
                    
                    if filter_today and not is_today:
                        continue
                        
                    if not any(p["url"] == link for p in posts):
                        posts.append({
                            "title": title.strip().replace("\n", " "),
                            "url": link,
                            "date": date_text.strip()
                        })
            
            return {
                "status": "success",
                "count": len(posts),
                "posts": posts[:20],
                "filter_today": filter_today
            }
        except Exception as e:
            logger.error(f"게시판 목록 추출 실패: {e}")
            return {"status": "error", "message": f"목록 추출 실패: {str(e)}"}

    async def list_my_cafes(self) -> Dict[str, Any]:
        """내가 가입한 카페 목록 확인"""
        page = await get_naver_page(self.browser_manager)
        # 최신 네이버 카페 홈 URL로 변경
        await page.goto("https://section.cafe.naver.com/ca-fe/home")
        await asyncio.sleep(2)
        
        current_url = page.url
        title = await page.title()
        logger.info(f"📍 현재 페이지: {title} ({current_url})")
        
        if "nid.naver.com" in current_url:
            return {"status": "error", "message": "로그인 페이지로 리다이렉트되었습니다. 세션이 만료된 것 같습니다."}

        cafes = []
        try:
            # 셀렉터 대기
            await page.wait_for_selector(".my_cafe_list, .cafe_name", timeout=10000)
            cafe_elements = await page.query_selector_all(".my_cafe_list .name, .cafe_name, .name")
            for el in cafe_elements:
                text = await el.inner_text()
                if text.strip():
                    cafes.append(text.strip())
            
            if not cafes:
                # 디버깅용: 본문 일부 출력
                body = await page.inner_text("body")
                logger.info(f"📄 페이지 본문 일부: {body[:500]}...")
                
        except Exception as e:
            logger.warning(f"카페 목록 추출 중 오류 (또는 카페 없음): {e}")
            
        return {"status": "success", "my_cafes": cafes, "url": current_url}

    async def find_recent_posts(self, url: str, max_days: int = 3) -> Dict[str, Any]:
        """최근 n일 내의 게시글 목록을 탐색 (오늘 -> 1일전 -> ... 순서)"""
        for day in range(max_days + 1):
            target_date = datetime.datetime.now() - datetime.timedelta(days=day)
            # 날짜 형식 보정 (마지막 점 제외하여 매칭 확률 제고)
            date_str = target_date.strftime("%Y.%m.%d")
            
            logger.info(f"📅 {day}일 전 게시글 탐색 중... ({date_str})")
            
            # get_board_posts를 호출 (오늘이면 filter_today=True, 아니면 날짜 문자열 필터링 위해 False)
            result = await self.get_board_posts(url, filter_today=(day == 0))
            logger.debug(f" {url} - {day}일 전 검색 결과: status={result.get('status')}, count={result.get('count')}")
            
            if result.get("status") == "success" and result.get("count", 0) > 0:
                logger.debug(f" {url} 필터링 시작 (대상 날짜: {date_str})")
                if day > 0:
                    for p in result["posts"]:
                        logger.debug(f" [Post] {p['title']} | Date: {p['date']}")
                    # 해당 날짜와 일치하는 글만 필터링
                    filtered_posts = [p for p in result["posts"] if date_str in p.get("date", "")]
                    if filtered_posts:
                        result["posts"] = filtered_posts
                        result["count"] = len(filtered_posts)
                        result["date_str"] = date_str
                        return result
                else:
                    logger.info(f"✅ 오늘 게시글 {result['count']}개 발견!")
                    result["date_str"] = date_str
                    return result
                    
        return {"status": "success", "count": 0, "posts": [], "date_str": "unknown"}

    async def fetch_external_content(self, url: str) -> str:
        """외부 뉴스 링크 등에 접속하여 본문 텍스트 추출 (헤드리스로 속도 최적화)"""
        # 브라우저 시작 보장
        browser = await self.browser_manager.start(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            logger.info(f"🔗 외부 링크 접속 중: {url}")
            await page.goto(url, timeout=20000)
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
            
            # 일반적인 뉴스 사이트 본문 셀렉터 시도
            content_selectors = ["article", "#articleBody", "#articleBodyContents", ".article_body", ".news_body", "main", ".article_view"]
            for sel in content_selectors:
                el = await page.query_selector(sel)
                if el:
                    text = await el.inner_text()
                    if len(text.strip()) > 200:
                        return text.strip()
            
            return await page.inner_text("body")
        except Exception as e:
            logger.warning(f"외부 링크 수집 실패 ({url}): {e}")
            return ""
        finally:
            await page.close()
            await context.close()

    async def analyze_theme_stocks(self) -> Dict[str, Any]:
        """메뉴 23(핵심뉴스)과 메뉴 86(오늘의 테마)을 분석하여 종합 데이터 생성"""
        results = {
            "key_news": [],
            "themes": [],
            "images": []
        }
        
        # 1. 메뉴 23: 핵심뉴스 수집
        news_url = "https://cafe.naver.com/f-e/cafes/26347614/menus/23?viewType=L"
        news_list = await self.find_recent_posts(news_url)
        processed_article_ids = set()
        
        if news_list["count"] > 0:
            for post in news_list["posts"][:2]: # 최신 2개만 분석 (시간 단축)
                article_id_match = re.search(r"articles/(\d+)", post["url"])
                if article_id_match:
                    article_id = article_id_match.group(1)
                    processed_article_ids.add(article_id)
                    post_data = await self.read_post("26347614", article_id)
                    if post_data["status"] == "success":
                        data = post_data["data"]
                        content = data["content"]
                        
                        # 외부 뉴스 링크 추출 (텍스트 매칭 + <a> 태그 링크 통합)
                        text_urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', content)
                        all_urls = data.get("links", []) + text_urls
                        
                        # 중복 제거 및 URL 정제
                        seen_urls = set()
                        unique_urls = []
                        for u in all_urls:
                            # 줄바꿈이나 공백 제거
                            clean_u = u.strip().replace("\n", "").replace("\r", "")
                            if clean_u and clean_u not in seen_urls:
                                seen_urls.add(clean_u)
                                unique_urls.append(clean_u)
                        
                        news_details = []
                        # 주요 뉴스 도메인 필터링 (최대 5개까지 수집)
                        news_domains = ["news.naver.com", "v.daum.net", "sedaily.com", "hankyung.com", "mk.co.kr", "biz.chosun.com"]
                        for url in unique_urls:
                            if len(news_details) >= 5: break
                            
                            if any(domain in url for domain in news_domains):
                                detail = await self.fetch_external_content(url)
                                if detail:
                                    news_details.append({"url": url, "detail": detail[:2000]})
                        
                        results["key_news"].append({
                            "title": data["title"],
                            "content": content,
                            "external_news": news_details,
                            "url": data["url"]
                        })
        
        # 2. 메뉴 86: 오늘의 테마 수집
        theme_url = "https://cafe.naver.com/f-e/cafes/26347614/menus/86?viewType=L"
        theme_list = await self.find_recent_posts(theme_url)
        
        if theme_list["count"] > 0:
            logger.debug(f" 메뉴 86 검색 결과 {len(theme_list['posts'])}개 글 발견")
            # 제목에 '테마', '주도', '특징'이 포함된 글 위주로 선택
            theme_posts = [p for p in theme_list["posts"] if any(k in p["title"] for k in ["테마", "주도", "특징"])]
            if not theme_posts: 
                theme_posts = theme_list["posts"]
            
            logger.debug(f" 필터링된 테마 관련글 수: {len(theme_posts)}")
            
            captured_count = 0
            for post in theme_posts:
                if captured_count >= 2: break # 최대 2개만
                
                article_id_match = re.search(r"articles/(\d+)", post["url"])
                if article_id_match:
                    article_id = article_id_match.group(1)
                    if article_id in processed_article_ids:
                        logger.debug(f" 중복 게시글 스킵: {post['title']}")
                        continue
                    
                    logger.debug(f" 테마 게시글 분석 시작: {post['title']}")
                    post_data = await self.read_post("26347614", article_id, analyze_vision=True)
                    if post_data["status"] == "success":
                        data = post_data["data"]
                        results["themes"].append({
                            "title": data["title"],
                            "content": data["content"],
                            "image_paths": data.get("image_paths", [])
                        })
                        results["images"].extend(data.get("image_paths", []))
                        captured_count += 1

        # 3. 데이터 요약 및 그룹화
        themes_found = {}
        for item in results["key_news"] + results["themes"]:
            title = item["title"]
            # 간단한 테마 분류
            if "반도체" in title: themes_found.setdefault("반도체", []).append(title)
            elif "AI" in title.upper() or "인공지능" in title: themes_found.setdefault("AI/인공지능", []).append(title)
            elif "2차전지" in title or "배터리" in title: themes_found.setdefault("2차전지", []).append(title)
            elif "바이오" in title: themes_found.setdefault("바이오", []).append(title)
            else: themes_found.setdefault("기타/종합", []).append(title)
        
        results["summary"] = {
            "target_date": news_list.get("date_str", "unknown"),
            "detected_themes": list(themes_found.keys()),
            "grouped_titles": themes_found
        }
        
        return {"status": "success", "data": results}

def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """네이버 카페 정보 수집 및 테마주 분석 도구.
    [사용 시점] 
    - 네이버 카페의 특정 게시글 내용을 읽거나 검색이 필요할 때
    - 국내 테마주(핵심뉴스, 오늘의 테마) 종합 분석 데이터가 필요할 때
    
    [파라미터]
    - action: "read"(게시글), "theme_analysis"(테마주 분석), "search"(검색), "board"(게시판), "list"(카페목록)
    - cafe_id: 카페 ID (action="read", "search" 시 필수)
    - article_id: 게시글 ID (action="read" 시 필수)
    - query: 검색어 (action="search" 시 필수)
    - url: 게시판 URL (action="board" 시 필수)
    - analyze_vision: true 설정 시 게시글 내 이미지를 분석 (action="read" 시 선택)
    
    [출력] 
    성공 시 {"status": "success", "data": {...}} 형식의 구조화된 데이터 반환
    """
    skill = NaverCafeSkill()
    # 별도 스레드에서 실행되므로 항상 새로운 루프를 생성하여 실행 가능
    return asyncio.run(skill.run(params))
