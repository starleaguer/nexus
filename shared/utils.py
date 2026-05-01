import re
import json
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    텍스트에서 JSON 객체를 찾아 파싱합니다.
    마크다운 코드 블록 우선 탐색 후, 일반 텍스트 내의 중괄호 블록을 탐색합니다.
    """
    if not text:
        return None

    # 1. 마크다운 코드 블록 우선 추출 (json 또는 일반 코드 블록)
    code_blocks = re.findall(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    
    potential_jsons = []
    if code_blocks:
        potential_jsons.extend(code_blocks)
    
    # 2. 일반 텍스트 내 JSON 블록 추출 (탐욕적/비탐욕적 매칭 병행)
    # 비탐욕적 매칭 (개별 작은 객체들)
    potential_jsons.extend(re.findall(r'(\{.*?\})', text, re.DOTALL))
    # 탐욕적 매칭 (가장 큰 블록 우선)
    raw_matches = re.findall(r'(\{.*\})', text, re.DOTALL)
    if raw_matches:
        potential_jsons.extend(raw_matches)
        
    for json_str in potential_jsons:
        try:
            # 불필요한 마크다운 태그 정제
            clean_json = re.sub(r'```(?:json)?\s*|\s*```', '', json_str).strip()
            parsed = json.loads(clean_json)
            
            if isinstance(parsed, dict):
                return parsed
        except:
            continue
            
    return None
