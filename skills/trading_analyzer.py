import sys
import os
from pathlib import Path
import json
import logging
import datetime
from typing import Dict, Any, Optional

# 로깅 설정
logger = logging.getLogger("TradingAnalyzerSkill")

# 프로젝트 루트 및 tmp 경로 추가 (kis_v2, make_korea_db 임포트용)
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TMP_DIR = PROJECT_ROOT / "tmp"
if str(TMP_DIR) not in sys.path:
# 의존성 임포트
try:
    import kis_v2
    import make_korea_db
    import FinanceDataReader as fdr
    import pandas as pd
except ImportError as e:
    logger.error(f"필수 라이브러리 또는 모듈을 임포트할 수 없습니다: {e}")

import ollama
from shared.config_loader import NexusConfig

class TradingAnalyzerSkill:
    """
    한국 주식 분석 및 트레이딩 지원 스킬
    """
    name = "trading_analyzer"
    description = "한국 주식 시세 조회, 재무 요약, 차트 분석 및 데이터베이스 관리 스킬"
    version = "1.1.0"

    def search_stock_code(self, name: str) -> str:
        """종목명으로 티커 코드 검색"""
        try:
            return make_korea_db.get_code_name(name)
        except:
            return "not found"

    def get_current_price(self, code: str) -> Dict[str, Any]:
        """현재가 및 52주 고저가 조회"""
        now = datetime.datetime.now()
        try:
            # 최근 10일치 데이터를 가져와서 마지막 종가 확인
            df = fdr.DataReader(code, (now - datetime.timedelta(days=10)).strftime('%Y%m%d'))
            if df.empty:
                return {"status": "error", "message": f"No data found for code {code}"}
            
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last
            
            # 52주 데이터
            df_year = fdr.DataReader(code, (now - datetime.timedelta(days=365)).strftime('%Y%m%d'))
            high_52 = df_year['High'].max()
            low_52 = df_year['Low'].min()
            
            return {
                "status": "success",
                "code": code,
                "current_price": int(last['Close']),
                "change_percent": round((last['Close'] - prev['Close']) / prev['Close'] * 100, 2),
                "high": int(last['High']),
                "low": int(last['Low']),
                "volume": int(last['Volume']),
                "high_52w": int(high_52),
                "low_52w": int(low_52)
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def analyze_stock(self, name_or_code: str) -> Dict[str, Any]:
        """연간 성과 분석 및 추세선 차트 생성"""
        try:
            result = kis_v2.single_annual(name_or_code)
            if result and result[0]:
                return {"status": "success", "analysis": result[1]}
            return {"status": "failed", "message": "분석 데이터를 가져오지 못했습니다."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_financial_summary(self, code: str) -> Dict[str, Any]:
        """재무 지표 요약 (PER, PBR, ROE 등)"""
        try:
            data = make_korea_db.snapshot(code)
            return {"status": "success", "financials": data}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """워커 실행 엔트리포인트"""
        query = params.get("query", "")
        action = params.get("action")
        target = params.get("target")

        # 자연어 쿼리만 온 경우 의도 분석 시도
        if not action and query:
            action, target = self._parse_intent(query)
            logger.info(f"의도 분석 결과: action={action}, target={target}")

        if not action or not target:
            return {"status": "error", "message": "분석 의도나 대상을 파악할 수 없습니다."}

        # 종목명/코드 정규화
        code = target if (target and target.isdigit() and len(target) == 6) else self.search_stock_code(target)
        if "not found" in code.lower() and action != "analyze":
            return {"status": "error", "message": f"'{target}' 종목 코드를 찾을 수 없습니다."}

        try:
            if action == "price":
                return self.get_current_price(code)
            elif action == "analyze":
                return self.analyze_stock(target) # analyze는 이름/코드 둘 다 지원
            elif action == "summary":
                return self.get_financial_summary(code)
            elif action == "headline":
                headline = kis_v2.get_stock_headline(code)
                return {"status": "success", "headline": headline or "정보 없음"}
            elif action == "refresh":
                make_korea_db.save_year_data(code)
                make_korea_db.save_tooja_data(code)
                return {"status": "success", "message": "DB 업데이트 완료"}
            
            return {"status": "error", "message": f"지원하지 않는 액션: {action}"}
        except Exception as e:
            logger.error(f"스킬 실행 중 오류: {e}")
            return {"status": "error", "message": str(e)}

    def _parse_intent(self, query: str) -> tuple:
        """Ollama를 사용하여 의도 분석"""
        model = NexusConfig.get_model("worker")
        prompt = f"""사용자 질문에서 한국 주식 분석 액션과 대상을 추출해.
        질문: "{query}"
        액션: price(시세), analyze(성과분석/차트), summary(재무/지표), headline(개요), refresh(업데이트)
        반드시 JSON만 응답: {{"action": "price", "target": "삼성전자"}}"""
        
        try:
            response = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
            content = response.get("message", {}).get("content", "")
            if "{" in content:
                data = json.loads(content[content.find("{"):content.rfind("}")+1])
                return data.get("action"), data.get("target")
        except:
            pass
        return None, None

def run(params: Dict[str, Any]) -> Dict[str, Any]:
    return TradingAnalyzerSkill().run(params)
ction": "price", "target": "삼성전자"}}
        """
        
        try:
            response = ollama.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}]
            )
            result_text = response.get("message", {}).get("content", "")
            if "{" in result_text and "}" in result_text:
                json_str = result_text[result_text.find("{"):result_text.rfind("}")+1]
                extracted = json.loads(json_str)
                return extracted.get("action"), extracted.get("target")
        except Exception as e:
            logger.warning(f"의도 분석 실패: {e}")
        
        return None, None

def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """워커 엔트리포인트"""
    skill = TradingAnalyzerSkill()
    return skill.run(params)

if __name__ == "__main__":
    # 테스트
    logging.basicConfig(level=logging.INFO)
    print(run({"query": "삼성전자 주가 알려줘"}))
    print(run({"query": "현대차 재무 요약해줘"}))
