import os
import json
import datetime
from pathlib import Path
from core.config_loader import NexusConfig

class LLMLogger:
    """LLM 요청 및 응답 과정을 파일로 기록하는 전용 로거"""
    
    LOG_DIR = NexusConfig.PROJECT_ROOT / "data" / "logs"
    LOG_FILE = LOG_DIR / "nexus_process.log"

    @classmethod
    def log_interaction(cls, tier: str, model: str, step: str, prompt: str, response: str):
        """인터랙션 기록"""
        try:
            if not cls.LOG_DIR.exists():
                cls.LOG_DIR.mkdir(parents=True, exist_ok=True)
                
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 로그 구분선 및 메타데이터
            entry = f"\n{'='*80}\n"
            entry += f"[{timestamp}] TIER: {tier} | MODEL: {model} | STEP: {step}\n"
            entry += f"{'-'*80}\n"
            entry += f"[PROMPT/INPUT]:\n{prompt}\n\n"
            entry += f"[RESPONSE/OUTPUT]:\n{response}\n"
            entry += f"{'='*80}\n"
            
            with open(cls.LOG_FILE, "a", encoding="utf-8") as f:
                f.write(entry)
                
        except Exception as e:
            # 로깅 실패가 메인 로직에 영향을 주지 않도록 함
            print(f"Error writing to process log: {e}")

    @classmethod
    def log_tool_usage(cls, tool_name: str, params: dict, result_summary: str):
        """도구 실행 결과 기록"""
        try:
            if not cls.LOG_DIR.exists():
                cls.LOG_DIR.mkdir(parents=True, exist_ok=True)
                
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            entry = f"\n{'>'*10} [TOOL EXECUTION] {tool_name} {'<'*10}\n"
            entry += f"[{timestamp}] PARAMS: {json.dumps(params, ensure_ascii=False)}\n"
            entry += f"[SUMMARY]: {result_summary}\n"
            entry += f"{'='*80}\n"
            
            with open(cls.LOG_FILE, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"Error writing tool log: {e}")
