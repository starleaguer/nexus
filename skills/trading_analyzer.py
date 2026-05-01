"""
한국 주식(KOSPI/KOSDAQ) 시세 및 기술적 분석 도구.
[사용 시점] 한국 주식의 현재가, 재무 지표, 차트 분석, 기업 개요가 필요할 때 사용.
[출력] 실시간 시세, 52주 고저가, 연간 성과 분석 데이터 및 차트 이미지 경로.
"""
import sys
import os
from pathlib import Path
import json
import logging
import datetime
from typing import Dict, Any, Optional

# 로깅 설정: 개별 basicConfig 제거 (시스템 설정 준수)
logger = logging.getLogger(__name__)

# 프로젝트 루트 및 tmp 경로 추가 (kis_v2, make_korea_db 임포트용)
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TMP_DIR = PROJECT_ROOT / "tmp"
if str(TMP_DIR) not in sys.path:
    sys.path.insert(0, str(TMP_DIR))

# 의존성 임포트
try:
    import tmp.kis_v2 as kis_v2
    import tmp.make_korea_db as make_korea_db
    import FinanceDataReader as fdr
    import pandas as pd
except ImportError as e:
    logger.error(f"필수 라이브러리 또는 모듈을 임포트할 수 없습니다: {e}")

import ollama
from core.config_loader import NexusConfig
from shared.utils import extract_json_from_text

class TradingAnalyzerSkill:
    """
    한국 주식 분석 및 트레이딩 지원 스킬
    """
    name = "trading_analyzer"
    description = "한국 주식 시세 조회, 재무 요약, 차트 분석 및 데이터베이스 관리 스킬"
    version = "1.1.0"

    def search_stock_code(self, name: str) -> str:
        """종목명으로 티커 코드 검색 (부분 일치 지원)"""
        try:
            # 1순위: 기존 JSON DB 검색 (완전 일치)
            code = make_korea_db.get_code_name(name)
            if code != name and code != "not found" and code.isnumeric():
                return code
                
            # 2순위: JSON DB 부분 일치 검색 (예: 하이닉스 -> SK하이닉스)
            json_path = PROJECT_ROOT / 'tmp' / 'stock_code.json'
            if json_path.exists():
                with open(json_path, 'r', encoding='utf-8') as f:
                    codes = json.load(f)
                    for stock_name, stock_code in codes.items():
                        if name in stock_name:
                            return stock_code

            # 3순위: FinanceDataReader로 실시간 검색
            df = fdr.StockListing('KRX')
            matched = df[df['Name'].str.contains(name, na=False)]
            if not matched.empty:
                return matched.iloc[0]['Code']
                
            return "not found"
        except Exception as e:
            logger.error(f"종목 코드 검색 실패: {e}")
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
                "change_percent": round((last['Close'] - prev['Close']) / prev['Close'] * 100, 2) if prev['Close'] > 0 else 0,
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
            if result and len(result) >= 2 and isinstance(result[0], str):
                code = result[0]
                # 차트 저장 경로는 kis_v2.show_chart의 명명 규칙과 일치해야 함
                chart_url = f"/static/charts/nexus_{code}.png"
                return {
                    "status": "success", 
                    "analysis": result[1],
                    "chart_url": chart_url
                }
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
        """Ollama를 사용하여 의도 분석 (2중 폴백 적용)"""
        model = NexusConfig.get_model("worker")
        urls = [NexusConfig.get_worker_url(), "http://localhost:11434"]
        
        prompt = f"""사용자 질문에서 한국 주식 분석 액션과 대상을 추출해.
        질문: "{query}"
        액션: price(시세), analyze(성과분석/차트), summary(재무/지표), headline(개요), refresh(업데이트)
        반드시 JSON만 응답: {{"action": "price", "target": "삼성전자"}}"""
        
        for url in urls:
            try:
                from shared.logger_utils import LLMLogger
                from ollama import Client
                import httpx
                
                # 모델 로딩(Cold Start) 시간을 고려하여 타임아웃 연장
                client = Client(host=url, timeout=httpx.Timeout(15.0))
                response = client.chat(model=model, messages=[{"role": "user", "content": prompt}])
                content = response.get("message", {}).get("content", "")
                
                LLMLogger.log_interaction("Skill Intent", model, f"Intent Analysis ({url})", prompt, content)
                data = extract_json_from_text(content)
                if data:
                    return data.get("action"), data.get("target")
            except Exception as e:
                logger.warning(f"⚠️ 의도 분석 실패 ({url}): {e}")
                continue

        # 모든 LLM 실패 시 규칙 기반 폴백 (Simplicity First)
        logger.info("🧩 LLM 실패로 규칙 기반 폴백 실행")
        return self._parse_intent_rule_based(query)

    def _parse_intent_rule_based(self, query: str) -> tuple:
        """키워드 기반 단순 의도 분석 (정교화)"""
        action = None
        target = None
        
        # 액션 키워드 매칭 (우선순위: 분석/요약 > 시세)
        if any(k in query for k in ["분석", "차트", "성과", "그래프"]): action = "analyze"
        elif any(k in query for k in ["재무", "지표", "요약", "성적"]): action = "summary"
        elif any(k in query for k in ["회사", "개요", "뭐하는", "정보"]): action = "headline"
        elif any(k in query for k in ["업데이트", "갱신", "최신화"]): action = "refresh"
        elif any(k in query for k in ["가격", "얼마", "시세", "주가", "현재가"]): action = "price"
        
        # 종목명 추출 시도 (2자 이상 한글)
        import re
        candidates = re.findall(r'[가-힣]{2,}', query)
        for cand in candidates:
            # "지금", "얼마야" 같은 일반 단어 제외를 위해 stock_code.json 활용
            code = self.search_stock_code(cand)
            if code != "not found":
                # 코드를 찾았으면, 해당 코드의 실제 이름을 target으로 설정 (부분 일치 대응)
                # target = cand 가 아니라 실제 매칭된 이름을 찾으면 좋겠지만, 
                # 여기서는 cand로 진행해도 search_stock_code가 나중에 처리함.
                target = cand
                break
        
        return action, target

def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """한국 주식(KOSPI/KOSDAQ) 개별 종목 분석 도구.
    [사용 시점] 
    - 특정 상장 기업(예: 삼성전자, SK하이닉스)의 실시간 주가, 재무제표, 차트 분석이 필요할 때
    - '테마주' 전체 분석이 아닌, '개별 종목'의 상세 정보가 필요할 때
    
    [파라미터]
    - action: "price"(현재가), "analyze"(차트/성과), "summary"(재무지표), "headline"(기업개요)
    - target: 구체적인 종목명 (필수, 예: "삼성전자"). '국내 테마주'와 같은 추상적 단어는 지원하지 않음.
    
    [출력] 
    성공 시 해당 종목의 상세 데이터 및 분석 결과 반환
    """
    skill = TradingAnalyzerSkill()
    return skill.run(params)

if __name__ == "__main__":
    # 테스트 시에만 로깅 설정
    logging.basicConfig(level=logging.INFO)
    print(run({"query": "삼성전자 주가 알려줘"}))
    print(run({"query": "현대차 재무 요약해줘"}))
