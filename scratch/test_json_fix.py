import sys
import os
import asyncio
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from shared.utils import extract_json_from_text

# Test case: LLM response with markdown and params wrapper
llm_response = """
전략을 수립했습니다.
```json
{
  "persona": "퀀트 투자 전략가",
  "intent": "현대차 기술적 분석",
  "strategy": "주가 차트 분석 진행",
  "required_tool": "trading_analyzer",
  "params": {"action": "analyze", "target": "현대차"},
  "intelligence_level": "high",
  "is_finished": false,
  "thought": "사용자가 현대차 분석을 원하므로 도구를 호출합니다."
}
```
"""

print("=== Raw Response ===")
print(llm_response)

print("\n=== Parsed JSON ===")
parsed = extract_json_from_text(llm_response)
import json
print(json.dumps(parsed, indent=2, ensure_ascii=False))

if parsed and "required_tool" in parsed:
    print("\n✅ SUCCESS: 'required_tool' found in parsed JSON.")
else:
    print("\n❌ FAILURE: 'required_tool' MISSING in parsed JSON.")
