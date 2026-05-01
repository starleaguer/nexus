"""
웹 검색 및 실시간 문서 데이터 추출 도구.
[사용 시점] 최신 뉴스, 기업 공식 문서, 일반적인 지식 검색이 필요할 때 사용.
[출력] 검색 결과 목록(제목, 링크, 스니펫) 및 개별 웹 페이지의 텍스트 본문 추출물.
"""
import logging
from typing import Dict, Any, List
import json
import time
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import warnings

# duckduckgo_search 패키지의 이름 변경 관련 경고 억제
warnings.filterwarnings("ignore", category=RuntimeWarning, module="duckduckgo_search")

logger = logging.getLogger(__name__)

class WebResearcher:
    """
    웹 검색 및 뉴스 수집 전문 스킬
    """
    def __init__(self):
        self.ddgs = DDGS()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }

    def search(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """DuckDuckGo 검색 실행"""
        try:
            logger.info(f"Web Search 실행: {query}")
            results = self.ddgs.text(query, max_results=max_results)
            return results
        except Exception as e:
            logger.error(f"Search Error: {e}")
            return []

    def fetch_content(self, url: str, max_length: int = 5000) -> str:
        """URL에서 본문 텍스트 추출 및 마크다운 변환"""
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 불필요한 태그 제거
            for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
                script.decompose()
            
            # 본문 추출 (간단한 로직)
            content = soup.get_text()
            # 마크다운 변환 (전체 HTML 대신 soup에서 정제된 결과 사용도 가능하나 여기서는 단순화)
            markdown = md(str(soup), heading_style="ATX")
            
            return markdown[:max_length] # 모델 컨텍스트 윈도우에 맞춰 자름
        except Exception as e:
            logger.error(f"Fetch Error ({url}): {e}")
            return f"Error fetching content: {str(e)}"

    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        query = params.get("query", "")
        if not query:
            return {"status": "error", "message": "Query is required"}
            
        # 모델 정보에 따른 Context Window 동적 할당
        model_info = params.get("current_model_info", {})
        provider = model_info.get("provider", "local")
        
        if provider in ["gemini", "anthropic"]:
            max_len = 40000  # API 모델은 긴 컨텍스트 지원
            logger.info("🧠 거대 컨텍스트 윈도우(API 모델) 감지: 40000자 수집")
        elif provider == "openai":
            max_len = 20000
        else:
            max_len = 6000   # Local / Worker 모델
            logger.info("💻 로컬/워커 모델 감지: 6000자로 텍스트 제한")
        
        # 1. 검색
        search_results = self.search(query)
        
        # 2. 각 결과에 대해 본문 수집 (시간 관계상 상위 3개만 깊게 수집)
        detailed_results = []
        for res in search_results[:3]:
            url = res.get("href") or res.get("link")
            if url:
                content = self.fetch_content(url, max_length=max_len)
                detailed_results.append({
                    "title": res.get("title"),
                    "url": url,
                    "snippet": res.get("body") or res.get("snippet"),
                    "content": content
                })
        
        return {
            "status": "success",
            "query": query,
            "results_count": len(search_results),
            "search_results": search_results, # 전체 결과 (스니펫 포함)
            "detailed_content": detailed_results # 상위 결과의 상세 본문
        }

def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """웹 검색 및 실시간 정보 수집 도구.
    [사용 시점] 
    - 최신 뉴스, 기업 공식 웹사이트 정보, 일반 상식 등 외부 데이터가 필요할 때
    - 주식 시세 외의 거시 경제 지표나 시장 여론(트렌드)을 파악할 때
    
    [파라미터]
    - query: 검색 키워드 (필수, 예: "엔비디아 최근 실적 발표 내용")
    
    [출력] 
    검색 결과 목록 및 주요 웹 페이지의 상세 본문(Markdown 형식) 반환
    """
    researcher = WebResearcher()
    return researcher.run(params)

if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.INFO)
    test_params = {"query": "Nvidia stock market news today"}
    print(json.dumps(run(test_params), indent=2, ensure_ascii=False))
