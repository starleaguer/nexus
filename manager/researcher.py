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
import shutil
import subprocess

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

    def _install_dependencies_with_uv(self, temp_path: Path, llm_packages: List[str]):
        """
        cloned repo의 파일들과 LLM 분석 결과를 바탕으로 uv add를 실행합니다.
        """
        # 중복 제거를 위한 set 사용
        packages_to_install = set(llm_packages) 

        # 1. requirements.txt 스캔 로직 강화
        req_file = temp_path / "requirements.txt"
        if req_file.exists():
            try:
                with open(req_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            # 버전 기호(==, >=, ~=) 제거 후 패키지명만 추출
                            pkg = line.split('==')[0].split('>=')[0].split('~=')[0].strip()
                            packages_to_install.add(pkg)
            except Exception as e:
                logger.error(f"requirements.txt 읽기 실패: {e}")

        # 2. 패키지 설치 실행
        if packages_to_install:
            logger.info(f"설치 시도할 패키지 리스트: {packages_to_install}")
            try:
                # uv add 명령어 실행 (프로젝트 루트의 pyproject.toml 기준)
                cmd = ["uv", "add"] + list(packages_to_install)
                result = subprocess.run(
                    cmd, 
                    cwd=NexusConfig.PROJECT_ROOT,
                    capture_output=True, 
                    text=True, 
                    check=True
                )
                logger.info(f"uv add 성공: {result.stdout.strip()}")
            except subprocess.CalledProcessError as e:
                logger.error(f"uv add 실패 (에러코드 {e.returncode}): {e.stderr.strip()}")
        else:
            logger.info("설치할 추가 의존성이 발견되지 않았습니다.")

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
        """Gemma를 사용하여 도구 적합성 평가"""
        
        system_prompt = """너는 로컬 AI 에이전트 생태계를 위한 'Tool Hunter'야.
새로운 분석 도구가 발견되면 다음 기준과 원칙에 따라 평가해줘.

[평가 기준]
1. 로컬 구동 가능성 (Local Runnable)
2. 에이전트 능력 확장성 (Agent Capability Expansion)
3. 파이썬 라이브러리 지원 또는 MCP 표준 준수 (Python/MCP Support)

반드시 아래 JSON 형식으로만 응답해:
{
    "is_suitable": true 혹은 false,
    "reasoning": "평가 이유 요약",
    "tool_name": "도구 이름",
    "description": "도구 설명",
    "type": "skill" 혹은 "mcp",
    "capabilities": ["기능1", "기능2"],
    "needed_packages": ["패키지1", "패키지2"]
}
"""
        user_prompt = f"Repository: {repo_info.get('full_name')}\nREADME: {readme_content[:2000]}"
        
        try:
            result = self.llm.chat(system_prompt, user_prompt, timeout=60)
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
            except Exception:
                return []
        return []

    def _save_candidates(self, candidates: List[Dict[str, Any]]):
        os.makedirs(self.candidate_file.parent, exist_ok=True)
        with open(self.candidate_file, "w", encoding="utf-8") as f:
            json.dump(candidates, f, ensure_ascii=False, indent=2)

    def save_candidate(self, repo_info: Dict[str, Any], analysis: Dict[str, Any]):
        """적합한 후보를 JSON 파일에 저장 (needed_packages 유실 방지)"""
        candidates = self._load_candidates()
        
        if any(c.get("repo") == repo_info.get("full_name") for c in candidates):
            return

        candidate_entry = {
            "repo": repo_info.get("full_name"),
            "url": repo_info.get("html_url"),
            "tool_name": analysis.get("tool_name", repo_info.get("name")),
            "description": analysis.get("description", repo_info.get("description")),
            "type": analysis.get("type", "skill"),
            "capabilities": analysis.get("capabilities", []),
            "needed_packages": analysis.get("needed_packages", []), # ★ 수정됨
            "reasoning": analysis.get("reasoning", ""),
            "status": "pending_approval"
        }
        
        candidates.append(candidate_entry)
        self._save_candidates(candidates)
        logger.info(f"후보 도구 저장: {candidate_entry['tool_name']}")

    def approve_candidate(self, tool_name: str) -> str:
        """후보 도구 승인 및 uv 기반 자동 설치/파일 추출 로직"""
        candidates = self._load_candidates()
        approved = next((c for c in candidates if c["tool_name"] == tool_name), None)
        
        if not approved:
            return "도구를 찾을 수 없습니다."

        # 경로 설정 및 파일명 정규화 (파이썬 모듈 호환성을 위해 하이픈을 언더스코어로 변경)
        safe_tool_name = tool_name.replace("-", "_")
        temp_path = NexusConfig.PROJECT_ROOT / "temp_tools" / tool_name
        skill_dest_dir = NexusConfig.PROJECT_ROOT / "worker" / "skills"
        skill_dest_file = skill_dest_dir / f"{safe_tool_name}.py"

        try:
            # 1. 클론 및 Git 기록 삭제 (Nested Repo 방지)
            if temp_path.exists():
                shutil.rmtree(temp_path)
            
            os.makedirs(temp_path.parent, exist_ok=True)
            logger.info(f"저장소 클론 중: {approved['url']}")
            subprocess.run(["git", "clone", "--depth", "1", approved["url"], str(temp_path)], check=True)
            
            if (temp_path / ".git").exists():
                shutil.rmtree(temp_path / ".git")

            # 2. 핵심 파일 추출 로직 개선 (entry point 후보 탐색)
            # 후보 1: 서버/메인 관련 이름, 후보 2: 도구 이름과 일치하는 파일, 후보 3: 가장 큰 파일
            all_py_files = list(temp_path.glob("**/*.py"))
            main_candidates = [f for f in all_py_files if f.name in ["server.py", "main.py", "app.py", f"{tool_name}.py", f"{safe_tool_name}.py"]]
            
            if main_candidates:
                entry_file = main_candidates[0]
            elif all_py_files:
                entry_file = sorted(all_py_files, key=lambda x: x.stat().st_size, reverse=True)[0]
            else:
                entry_file = None

            if entry_file:
                os.makedirs(skill_dest_dir, exist_ok=True)
                shutil.copy(entry_file, skill_dest_file)
                logger.info(f"Skill 파일 추출 완료: {skill_dest_file} (원본: {entry_file.name})")
            else:
                return "Python 파일을 찾을 수 없어 설치를 중단합니다."

            # 3. uv를 이용한 의존성 자동 추가
            llm_pkgs = approved.get("needed_packages", [])
            self._install_dependencies_with_uv(temp_path, llm_pkgs)

            # 4. Manifest 업데이트
            manifest = NexusConfig.load_manifest()
            tool_type = approved.get("type", "skill")
            
            new_entry = {
                "name": safe_tool_name, # 매니페스트에도 정규화된 이름 사용
                "description": approved["description"],
                "entry": f"worker/skills/{safe_tool_name}.py",
                "capabilities": approved["capabilities"]
            }
            
            # 중복 체크 후 추가
            target_list = manifest["tools"].setdefault("skills" if tool_type == "skill" else "mcp", [])
            if not any(t["name"] == safe_tool_name for t in target_list):
                target_list.append(new_entry)
                
            with open(self.manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            
            # 5. 후보 목록에서 제거 및 상태 변경
            approved["status"] = "approved"
            self._save_candidates(candidates)
            
            return f"'{tool_name}' 도구가 성공적으로 설치 및 등록되었습니다."
            
        except Exception as e:
            logger.error(f"설치 중 오류 발생: {e}")
            return f"설치 실패: {str(e)}"

    def reject_candidate(self, tool_name: str) -> bool:
        """후보 도구 거절 (목록에서 삭제)"""
        candidates = self._load_candidates()
        initial_len = len(candidates)
        
        # 목록에서 해당 도구 제거 (또는 상태를 'rejected'로 변경)
        # 여기서는 목록을 깔끔하게 유지하기 위해 제거합니다.
        candidates = [c for c in candidates if c["tool_name"] != tool_name]
        
        if len(candidates) < initial_len:
            self._save_candidates(candidates)
            logger.info(f"후보 도구 거절됨: {tool_name}")
            return True
        return False

    async def run_research_cycle(self, custom_queries: List[str] = None):
        """탐색 사이클 실행"""
        queries = []
        if custom_queries:
            # LLM을 사용하여 자연어 입력을 GitHub 검색 쿼리로 변환
            for custom_query in custom_queries:
                system_prompt = "너는 GitHub 검색 전문가야. 사용자의 요구사항에 맞는 Python 도구나 MCP 서버를 찾기 위한 검색 키워드를 생성해."
                user_prompt = f"""
사용자 요구사항: "{custom_query}"

이 요구사항을 만족하는 파이썬 라이브러리나 MCP 서버를 GitHub에서 찾기 위한 가장 효과적인 검색 키워드 1~2개를 제안해 줘.
예를 들어 'mcp-server stock', 'python volume profile' 처럼 영어 키워드 위주로 만들어야 해.
반드시 아래 JSON 형식으로만 응답해 (다른 설명 금지):
{{
    "queries": ["keyword1 keyword2", "mcp-server keyword3"]
}}
"""
                try:
                    result = self.llm.chat(system_prompt, user_prompt, timeout=30)
                    if "{" in result and "}" in result:
                        json_str = result[result.find("{"):result.rfind("}")+1]
                        parsed = json.loads(json_str)
                        optimized = parsed.get("queries", [])
                        queries.extend(optimized)
                        logger.info(f"자연어 '{custom_query}' -> 최적화된 검색어: {optimized}")
                    else:
                        queries.append(custom_query)
                except Exception as e:
                    logger.error(f"검색어 변환 실패: {e}")
                    queries.append(custom_query)
        else:
            queries = ["mcp-server stock finance", "stock analysis library python"]

        logger.info(f"탐색 사이클 시작 (최종 검색어: {queries})")
        
        for query in queries:
            repos = await self.search_github_repositories(query=query)
            for repo in repos:
                if any(c.get("repo") == repo.get("full_name") for c in self._load_candidates()):
                    continue
                readme = await self.get_readme(repo.get("full_name"))
                if readme:
                    analysis = self.analyze_tool_with_llm(repo, readme)
                    if analysis.get("is_suitable"):
                        self.save_candidate(repo, analysis)
                await asyncio.sleep(2)

    def start_scheduler(self):
        self.scheduler.add_job(self.run_research_cycle, 'cron', hour=3)
        self.scheduler.start()

if __name__ == "__main__":
    async def test():
        hunter = ToolHunter()
        await hunter.run_research_cycle()
    asyncio.run(test())