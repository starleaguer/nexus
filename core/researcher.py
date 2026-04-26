"""
Researcher Agent (The Tool Hunter)
새로운 분석 도구를 찾아 평가하고 매니페스트에 등록할 수 있도록 돕는 에이전트.
통합 아키텍처: 모든 도구는 skills/ 폴더 내부의 개별 패키지로 관리됨.
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
from core.config_loader import NexusConfig
from core.manager_core import OllamaClient

logger = logging.getLogger(__name__)

class ToolHunter:
    """새로운 분석 도구를 탐색하고 평가하는 에이전트"""
    
    def __init__(self):
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.llm = OllamaClient()
        self.candidate_file = NexusConfig.PROJECT_ROOT / "data" / "candidate_tools.json"
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
        packages_to_install = set(llm_packages) 

        req_file = temp_path / "requirements.txt"
        if req_file.exists():
            try:
                with open(req_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            pkg = line.split('==')[0].split('>=')[0].split('~=')[0].strip()
                            packages_to_install.add(pkg)
            except Exception as e:
                logger.error(f"requirements.txt 읽기 실패: {e}")

        if packages_to_install:
            logger.info(f"설치 시도할 패키지 리스트: {packages_to_install}")
            try:
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

    async def search_github_repositories(self, query: str = "mcp-server stock", limit: int = 5) -> List[Dict[str, Any]]:
        url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc"
        async with aiohttp.ClientSession(headers=self._get_headers()) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("items", [])[:limit]
                return []

    async def get_readme(self, repo_full_name: str) -> Optional[str]:
        url = f"https://api.github.com/repos/{repo_full_name}/readme"
        async with aiohttp.ClientSession(headers=self._get_headers()) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("content"):
                        return base64.b64decode(data["content"]).decode('utf-8')
                return None

    def analyze_tool_with_llm(self, repo_info: Dict[str, Any], readme_content: str) -> Dict[str, Any]:
        system_prompt = """너는 'Tool Hunter'야. 도구를 분석하여 JSON 형식으로만 응답해."""
        user_prompt = f"Repository: {repo_info.get('full_name')}\nREADME: {readme_content[:2000]}"
        try:
            result = self.llm.chat(system_prompt, user_prompt, timeout=60)
            if "{" in result and "}" in result:
                return json.loads(result[result.find("{"):result.rfind("}")+1])
        except: pass
        return {"is_suitable": False}

    def _load_candidates(self) -> List[Dict[str, Any]]:
        if self.candidate_file.exists():
            try:
                with open(self.candidate_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except: pass
        return []

    def _save_candidates(self, candidates: List[Dict[str, Any]]):
        os.makedirs(self.candidate_file.parent, exist_ok=True)
        with open(self.candidate_file, "w", encoding="utf-8") as f:
            json.dump(candidates, f, ensure_ascii=False, indent=2)

    def save_candidate(self, repo_info: Dict[str, Any], analysis: Dict[str, Any]):
        candidates = self._load_candidates()
        if any(c.get("repo") == repo_info.get("full_name") for c in candidates): return
        candidate_entry = {
            "repo": repo_info.get("full_name"),
            "url": repo_info.get("html_url"),
            "tool_name": analysis.get("tool_name", repo_info.get("name")),
            "description": analysis.get("description", repo_info.get("description")),
            "type": analysis.get("type", "skill"),
            "capabilities": analysis.get("capabilities", []),
            "needed_packages": analysis.get("needed_packages", []),
            "status": "pending_approval"
        }
        candidates.append(candidate_entry)
        self._save_candidates(candidates)

    def approve_candidate(self, tool_name: str) -> str:
        """도구 승인 및 통합 폴더 구조 설치"""
        candidates = self._load_candidates()
        approved = next((c for c in candidates if c["tool_name"] == tool_name), None)
        if not approved: return "도구를 찾을 수 없습니다."

        safe_tool_name = tool_name.replace("-", "_")
        # 통합 경로: skills/tool_name/
        tool_dir = NexusConfig.PROJECT_ROOT / "skills" / safe_tool_name
        src_dir = tool_dir / "src"
        
        try:
            if tool_dir.exists(): shutil.rmtree(tool_dir)
            os.makedirs(src_dir, exist_ok=True)
            
            # 1. src 폴더에 클론
            subprocess.run(["git", "clone", "--depth", "1", approved["url"], str(src_dir)], check=True)
            if (src_dir / ".git").exists(): shutil.rmtree(src_dir / ".git")

            # 2. 래퍼(Wrapper) 코드 생성 (__init__.py)
            all_py_files = list(src_dir.glob("**/*.py"))
            main_candidates = [f for f in all_py_files if f.name in ["server.py", "main.py", "app.py", f"{tool_name}.py"]]
            entry_file = main_candidates[0] if main_candidates else (all_py_files[0] if all_py_files else None)

            if not entry_file: return "Python 파일을 찾을 수 없습니다."
            
            # __init__.py에 기본 래퍼 로직 작성
            rel_entry = entry_file.relative_to(tool_dir)
            module_path = str(rel_entry).replace("/", ".").replace(".py", "")
            
            wrapper_code = f"""
import logging
from .src.{module_path.split('.src.')[-1]} import run as original_run

logger = logging.getLogger(__name__)

def run(params):
    \"\"\"{approved['description']}\"\"\"
    try:
        # 여기에 원본 소스의 진입점 함수 호출 로직 작성
        # 기본적으로 original_run이 있다고 가정하거나, 
        # 필요시 LLM이 이 파일을 다시 작성하도록 유도할 수 있음
        return original_run(params)
    except Exception as e:
        logger.error(f"Error executing {safe_tool_name}: {{e}}")
        return {{"error": str(e)}}
"""
            with open(tool_dir / "__init__.py", "w", encoding="utf-8") as f:
                f.write(wrapper_code)

            # 3. 의존성 설치
            self._install_dependencies_with_uv(src_dir, approved.get("needed_packages", []))

            # 4. Manifest 업데이트
            manifest = NexusConfig.load_manifest()
            tool_type = approved.get("type", "skill")
            new_entry = {
                "name": safe_tool_name,
                "description": approved["description"],
                "entry": f"skills/{safe_tool_name}", # 이제 폴더가 패키지임
                "capabilities": approved["capabilities"]
            }
            target_list = manifest["tools"].setdefault("skills" if tool_type == "skill" else "mcp", [])
            if not any(t["name"] == safe_tool_name for t in target_list):
                target_list.append(new_entry)
            with open(self.manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            
            approved["status"] = "approved"
            self._save_candidates(candidates)
            return f"'{tool_name}' 설치 완료 (경로: skills/{safe_tool_name})"
            
        except Exception as e:
            return f"설치 실패: {str(e)}"

    def reject_candidate(self, tool_name: str) -> bool:
        candidates = self._load_candidates()
        candidates = [c for c in candidates if c["tool_name"] != tool_name]
        self._save_candidates(candidates)
        return True

    async def run_research_cycle(self, custom_queries: List[str] = None):
        queries = custom_queries or ["mcp-server stock", "python financial analysis"]
        for query in queries:
            repos = await self.search_github_repositories(query=query)
            for repo in repos:
                readme = await self.get_readme(repo.get("full_name"))
                if readme:
                    analysis = self.analyze_tool_with_llm(repo, readme)
                    if analysis.get("is_suitable"):
                        self.save_candidate(repo, analysis)
            await asyncio.sleep(1)

if __name__ == "__main__":
    hunter = ToolHunter()
    asyncio.run(hunter.run_research_cycle())