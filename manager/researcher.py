"""
Researcher Agent (The Tool Hunter)
새로운 분석 도구를 찾아 평가하고 매니페스트에 등록할 수 있도록 돕는 에이전트.
"""
import asyncio
import json
import os
import base64
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import sys

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 설정 공유 모듈 로드
from shared.config_loader import NexusConfig
from manager.manager_core import OllamaClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class ToolHunter:
    """새로운 분석 도구를 탐색하고 평가하는 에이전트"""
    
    def __init__(self):
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.llm = OllamaClient()
        self.candidate_file = NexusConfig.PROJECT_ROOT / "shared" / "candidate_tools.json"
        self.manifest_file = NexusConfig.MANIFEST_PATH
        self.scheduler = AsyncIOScheduler()
        
    def _get_headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"
        return headers

    async def search_github_repositories(self, query: str = "mcp-server stock", limit: int = 5) -> List[Dict[str, Any]]:
        """GitHub API를 사용하여 저장소 검색"""
        url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc"
        
        async with aiohttp.ClientSession(headers=self._get_headers()) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("items", [])[:limit]
                elif response.status == 403:
                    logger.warning("GitHub API rate limit exceeded.")
                    return []
                else:
                    logger.error(f"GitHub Search API Error: {response.status}")
                    return []

    async def get_readme(self, repo_full_name: str) -> Optional[str]:
        """저장소의 README.md 내용을 가져옴"""
        url = f"https://api.github.com/repos/{repo_full_name}/readme"
        
        async with aiohttp.ClientSession(headers=self._get_headers()) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("content"):
                        return base64.b64decode(data["content"]).decode('utf-8')
                return None

    def analyze_tool_with_llm(self, repo_info: Dict[str, Any], readme_content: str) -> Dict[str, Any]:
        """Gemma-26B를 사용하여 도구 적합성 평가"""
        
        system_prompt = """너는 로컬 AI 에이전트 생태계를 위한 'Tool Hunter'야.
새로운 분석 도구가 발견되면 다음 기준과 원칙에 따라 평가해줘.

[평가 기준]
1. 로컬 구동 가능성 (Local Runnable)
2. 주식/시장 데이터 관련성 (Stock/Market Data Relevance)
3. 파이썬 라이브러리 지원 여부 (Python Library Support)

[핵심 원칙]
Principle 1: Low-Latency & Local-First (외부 유료 API(OpenAI, Anthropic 등) 필수 요구 시 감점)
Principle 2: Structural Data over News (단순 가십성 뉴스 크롤러보다는 재무/수급 등 구조적 데이터 선호)
Principle 3: Composability (다른 에이전트와 결합하기 쉬운 Class/Function 기반 모듈형 구조 선호)

반드시 아래 JSON 형식으로만 응답해:
{
    "is_suitable": true 혹은 false,
    "reasoning": "평가 이유 요약",
    "tool_name": "도구 이름",
    "description": "도구 설명",
    "type": "skill" 혹은 "mcp",
    "capabilities": ["가능한 기능1", "가능한 기능2"]
}
"""
        
        user_prompt = f"""
Repository: {repo_info.get('full_name')}
Description: {repo_info.get('description')}
Stars: {repo_info.get('stargazers_count')}
URL: {repo_info.get('html_url')}

[README 내용 일부]
{readme_content[:3000]}...

이 도구가 우리의 로컬 AI 에이전트의 Skill이나 MCP 서버로 적합한지 평가해줘. JSON으로만 응답해.
"""
        
        try:
            result = self.llm.chat(system_prompt, user_prompt, timeout=NexusConfig.get_timeout("ollama", 60))
            
            # JSON 파싱 (방어적 코드)
            if "{" in result and "}" in result:
                json_str = result[result.find("{"):result.rfind("}")+1]
                return json.loads(json_str)
        except Exception as e:
            logger.error(f"LLM 분석 실패: {e}")
            
        return {"is_suitable": False, "reasoning": "분석 실패"}

    def _load_candidates(self) -> List[Dict[str, Any]]:
        if self.candidate_file.exists():
            try:
                with open(self.candidate_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return []
        return []

    def _save_candidates(self, candidates: List[Dict[str, Any]]):
        with open(self.candidate_file, "w", encoding="utf-8") as f:
            json.dump(candidates, f, ensure_ascii=False, indent=2)

    def save_candidate(self, repo_info: Dict[str, Any], analysis: Dict[str, Any]):
        """적합한 후보를 JSON 파일에 저장"""
        candidates = self._load_candidates()
        
        # 중복 체크
        if any(c.get("repo") == repo_info.get("full_name") for c in candidates):
            logger.info(f"이미 등록된 후보: {repo_info.get('full_name')}")
            return

        candidate_entry = {
            "repo": repo_info.get("full_name"),
            "url": repo_info.get("html_url"),
            "tool_name": analysis.get("tool_name", repo_info.get("name")),
            "description": analysis.get("description", repo_info.get("description")),
            "type": analysis.get("type", "skill"),
            "capabilities": analysis.get("capabilities", []),
            "reasoning": analysis.get("reasoning", ""),
            "status": "pending_approval"
        }
        
        candidates.append(candidate_entry)
        self._save_candidates(candidates)
        logger.info(f"새로운 후보 도구 저장됨: {candidate_entry['tool_name']}")

    async def run_research_cycle(self):
        """탐색 사이클 실행"""
        logger.info("탐색 사이클 시작...")
        
        queries = ["mcp-server stock", "mcp-server finance", "stock analysis toolkit"]
        for query in queries:
            logger.info(f"검색어: {query}")
            repos = await self.search_github_repositories(query=query, limit=3)
            
            for repo in repos:
                repo_name = repo.get("full_name")
                logger.info(f"저장소 분석 중: {repo_name}")
                
                # 중복 검색 방지
                candidates = self._load_candidates()
                if any(c.get("repo") == repo_name for c in candidates):
                    continue
                
                readme = await self.get_readme(repo_name)
                if not readme:
                    logger.info(f"README 없음: {repo_name}")
                    continue
                
                analysis = self.analyze_tool_with_llm(repo, readme)
                
                if analysis.get("is_suitable"):
                    self.save_candidate(repo, analysis)
                
                # API Limit 보호를 위한 대기
                await asyncio.sleep(2)
                
        logger.info("탐색 사이클 완료.")

    def approve_candidate(self, tool_name: str) -> str:
        """후보 도구 승인 및 설치 명령어 생성"""
        candidates = self._load_candidates()
        approved = None
        
        for c in candidates:
            if c.get("tool_name") == tool_name and c.get("status") == "pending_approval":
                approved = c
                break
                
        if not approved:
            return "승인할 수 있는 도구를 찾지 못했습니다."
            
        # Manifest 업데이트
        manifest = NexusConfig.load_manifest()
        tool_type = approved.get("type", "skill")
        
        new_entry = {
            "name": approved["tool_name"],
            "description": approved["description"],
            "entry": f"worker/skills/{approved['tool_name']}.py", # 임시 경로
            "capabilities": approved["capabilities"],
            "repo_url": approved["url"]
        }
        
        if tool_type == "skill":
            manifest["tools"].setdefault("skills", []).append(new_entry)
        else:
            manifest["tools"].setdefault("mcp", []).append(new_entry)
            
        with open(self.manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
            
        # 상태 업데이트
        approved["status"] = "approved"
        self._save_candidates(candidates)
        
        # 설치 명령어 생성
        install_cmd = f"git clone {approved['url']} temp_tools/{approved['tool_name']} && echo '수동으로 코드를 worker/skills/로 옮기고 의존성을 설치하세요.'"
        
        return f"[승인 완료] {tool_name}이(가) manifest에 추가되었습니다.\n권장 설치 명령어:\n{install_cmd}"

    def start_scheduler(self):
        """하루 한 번 실행되도록 스케줄러 설정"""
        self.scheduler.add_job(self.run_research_cycle, 'cron', hour=3, minute=0)
        self.scheduler.start()
        logger.info("Researcher 스케줄러가 시작되었습니다 (매일 03:00 실행).")

# ==================== 테스트/수동 실행 ====================
if __name__ == "__main__":
    async def manual_run():
        hunter = ToolHunter()
        await hunter.run_research_cycle()
        
    asyncio.run(manual_run())
