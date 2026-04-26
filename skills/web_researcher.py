import logging
from typing import Dict, Any, List
import json
import time
from duckduckgo_search import DDGS
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

logger = logging.getLogger(__name__)

class WebResearcher:
    """
    웹 검색 및 뉴스 수집 전문 스킬
    """
    def __init__(self):
        self.ddgs = DDGS()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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

    def fetch_content(self, url: str) -> str:
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
            
            return markdown[:5000] # 너무 길면 자름
        except Exception as e:
            logger.error(f"Fetch Error ({url}): {e}")
            return f"Error fetching content: {str(e)}"

    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        query = params.get("query", "")
        if not query:
            return {"status": "error", "message": "Query is required"}
        
        # 1. 검색
        search_results = self.search(query)
        
        # 2. 각 결과에 대해 본문 수집 (시간 관계상 상위 3개만 깊게 수집)
        detailed_results = []
        for res in search_results[:3]:
            url = res.get("href") or res.get("link")
            if url:
                content = self.fetch_content(url)
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
    researcher = WebResearcher()
    return researcher.run(params)

if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.INFO)
    test_params = {"query": "Nvidia stock market news today"}
    print(json.dumps(run(test_params), indent=2, ensure_ascii=False))
