"""
Nexus Architect (Auto-Coder) Skill
시스템 소스 코드를 읽고, LLM을 사용하여 수정 사항(예: 보안 검수 로직 추가)을 반영한 뒤,
자체 검증(Self-Review)을 거쳐 안전하게 파일 시스템에 덮어쓰는 스킬입니다.
"""
import os
import json
import shutil
from pathlib import Path
from typing import Dict, Any, List

# 설정 모듈 로드 (worker_api.py와 동일한 환경을 가정)
import sys
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from manager.manager_core import OllamaClient
import logging

logger = logging.getLogger(__name__)

class Skill:
    def __init__(self):
        self.llm = OllamaClient() # 매니페스트/환경변수에 설정된 모델 사용 (ManagerCore 재사용)
        self.target_dir = PROJECT_ROOT / "worker" / "skills"

    def _find_target_files(self, query: str) -> List[Path]:
        """쿼리 분석 또는 단순 검색을 통해 수정 대상 파일을 찾습니다."""
        # 초기 버전: 쿼리에서 특정 파일명을 언급했는지 확인 (예: "kospi_kosdaq_stock_server 파일에...")
        targets = []
        for py_file in self.target_dir.glob("*.py"):
            if py_file.name == "__init__.py" or py_file.name == "nexus_architect.py":
                continue
            # 일단 쿼리에 파일 이름(확장자 제외)이 포함되어 있으면 대상, 아니면 모든 파일 대상 (실제 환경에서는 더 정교한 타겟팅 필요)
            if py_file.stem in query:
                targets.append(py_file)
        
        # 파일명을 명시하지 않은 경우 안전을 위해 최근 수정되거나 주요 파일 하나만 대상으로 잡거나 실패 처리
        # 여기서는 테스트/시연을 위해 모든 스킬 파일 대상 (현실에선 위험하므로 명시된 것만)
        return targets if targets else list(self.target_dir.glob("*.py"))[:1] # 못 찾으면 첫번째 파일 (임시)

    def _generate_code(self, original_code: str, query: str, filename: str) -> str:
        """LLM을 사용하여 코드를 수정합니다."""
        system_prompt = f"""너는 Nexus 시스템의 최고 코드 아키텍트야.
다음 파이썬 파일({filename})의 원본 코드를 읽고, 사용자의 요구사항에 맞게 코드를 수정해.
오직 수정된 완전한 파이썬 코드 전체만 응답해. 마크다운 코드 블록(```python ... ```)으로 감싸서 출력해."""
        
        user_prompt = f"""사용자 요구사항: {query}

[원본 코드]
```python
{original_code}
```

수정된 전체 파이썬 코드를 작성해줘."""
        
        result = self.llm.chat(system_prompt, user_prompt, timeout=120)
        return self._extract_code(result)

    def _verify_code(self, original_code: str, modified_code: str, query: str) -> tuple[bool, str]:
        """수정된 코드가 요구사항을 충족하는지 자체 검증(Self-Review)합니다."""
        system_prompt = """너는 엄격한 코드 리뷰어(Gatekeeper)야.
원본 코드와 수정된 코드를 비교하여, 사용자의 요구사항이 올바르게 반영되었는지, 파이썬 문법 오류나 기존 로직 훼손이 없는지 검토해.
반드시 아래 JSON 형식으로만 응답해:
{
    "is_valid": true 혹은 false,
    "reason": "검토 결과 설명 (구체적인 이유)"
}"""
        
        user_prompt = f"""사용자 요구사항: {query}

[원본 코드의 일부]
{original_code[:1000]}... (생략됨)

[수정된 코드의 일부]
{modified_code[:1500]}... (생략됨)

위 코드를 검토해줘."""
        
        result = self.llm.chat(system_prompt, user_prompt, timeout=60)
        try:
            if "{" in result and "}" in result:
                json_str = result[result.find("{"):result.rfind("}")+1]
                parsed = json.loads(json_str)
                return parsed.get("is_valid", False), parsed.get("reason", "검증 실패")
        except:
            pass
        return False, "JSON 파싱 실패로 검증을 통과하지 못했습니다."

    def _extract_code(self, llm_response: str) -> str:
        """LLM 응답에서 파이썬 코드 블록을 추출합니다."""
        if "```python" in llm_response:
            code = llm_response.split("```python")[1].split("```")[0].strip()
            return code
        elif "```" in llm_response:
            code = llm_response.split("```")[1].split("```")[0].strip()
            return code
        return llm_response.strip()

    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        query = params.get("query", "")
        if not query:
            return {"error": "요청 사항(query)이 없습니다."}

        target_files = self._find_target_files(query)
        if not target_files:
            return {"error": "수정할 대상 파일을 찾지 못했습니다."}

        results = []
        for file_path in target_files:
            try:
                # 1. 파일 읽기
                with open(file_path, "r", encoding="utf-8") as f:
                    original_code = f.read()

                logger.info(f"[Architect] 코드 생성 시작: {file_path.name}")
                
                # 2. 코드 생성
                modified_code = self._generate_code(original_code, query, file_path.name)
                if not modified_code:
                    results.append({"file": file_path.name, "status": "failed", "reason": "코드 생성 실패"})
                    continue

                # 3. 자체 검증 (Self-Review)
                logger.info(f"[Architect] 코드 검증 시작: {file_path.name}")
                is_valid, review_reason = self._verify_code(original_code, modified_code, query)

                if not is_valid:
                    results.append({"file": file_path.name, "status": "rejected", "reason": f"검증 반려: {review_reason}"})
                    continue

                # 4. 백업 생성 (.bak)
                backup_path = str(file_path) + ".bak"
                shutil.copy2(file_path, backup_path)
                
                # 5. 파일 덮어쓰기
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(modified_code)

                results.append({
                    "file": file_path.name, 
                    "status": "success", 
                    "backup": backup_path,
                    "review_comment": review_reason
                })
                logger.info(f"[Architect] 파일 업데이트 완료: {file_path.name}")

            except Exception as e:
                logger.error(f"[Architect] 에러 발생 ({file_path.name}): {e}")
                results.append({"file": file_path.name, "status": "error", "reason": str(e)})

        # 최종 결과 요약
        success_count = sum(1 for r in results if r["status"] == "success")
        return {
            "summary": f"총 {len(target_files)}개 파일 중 {success_count}개 성공적으로 업데이트됨.",
            "details": results
        }
