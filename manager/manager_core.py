"""
Manager Core - MacBook에서 실행되는 LangGraph 메인 로직
Gemma-27B(Ollama)를 사용한 중앙 통제 시스템
방어적 코딩 적용: 네트워크 병목, 서버 다운 등 예외 상황 처리
"""
from typing import Dict, Any, List, Optional
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
import asyncio
import os
import json
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# memory_manager import
from manager.memory_manager import MemoryManager


# ==================== 설정 ====================
class Config:
    """설정"""
    MAX_RETRIES = 3           # 최대 재시도 횟수
    RETRY_DELAY = 2           # 재시도 간격 (초)
    WORKER_TIMEOUT = 30       # Worker 요청 타임아웃 (초)
    OLLAMA_TIMEOUT = 20       # Ollama 요청 타임아웃 (초)


# ==================== AgentState 정의 ====================
class AgentState(dict):
    """에이전트 상태"""
    # 사용자 입력
    user_input: str
    user_id: str
    
    # 선택된 도구
    selected_tool: Optional[str]
    tool_params: Optional[Dict[str, Any]]
    
    # 워커 결과
    worker_result: Optional[Dict[str, Any]]
    worker_summary: Optional[str]
    
    # 적용된 원칙
    applied_principles: List[Dict[str, Any]]
    
    # 최종 리포트
    final_report: Optional[str]
    
    # 오류
    error: Optional[str]


# ==================== LLM 클라이언트 (방어적) ====================
class OllamaClient:
    """Ollama Gemma-27B 클라이언트 (방어적 코딩)"""
    
    def __init__(self, model: str = "gemma2:27b"):
        self.model = model
    
    def chat(self, system: str, user: str, timeout: int = Config.OLLAMA_TIMEOUT) -> str:
        """채팅 응답 생성 (타임아웃 처리)"""
        import ollama
        
        try:
            # 타임아웃을 위한 asyncio 사용
            response = asyncio.wait_for(
                asyncio.to_thread(
                    ollama.chat,
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user}
                    ]
                ),
                timeout=timeout
            )
            return response["message"]["content"]
        except asyncio.TimeoutError:
            logger.error(f"Ollama 타임아웃 ({timeout}초)")
            return "분석 시간이 초과되었습니다. 다시 시도해 주세요."
        except Exception as e:
            logger.error(f"Ollama 오류: {e}")
            return f"AI 분석 중 오류가 발생했습니다: {str(e)[:100]}"
    
    def analyze_intent(self, user_input: str, principles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """의도 분석"""
        principles_text = "\n".join([
            f"- {p.get('content', '')}" 
            for p in principles
        ]) if principles else "적용된 원칙 없음"
        
        system = """너는 투자 분석 전문가야. 
사용자의 질문에서 투자 의도를 분석하고 적절한 도구를 선택해줘.
응답은 JSON 형태로 반환해:
{
    "intent": "분석된 의도",
    "required_tool": "필요한 도구 이름",
    "params": {"키": "값"}
}"""
        
        user = f"""사용자 질문: {user_input}

적용 가능한 원칙:
{principles_text}

의도를 분석하고 도구를 선택해줘."""
        
        result = self.chat(system, user)
        
        # JSON 파싱 시도
        try:
            if "{" in result and "}" in result:
                json_str = result[result.find("{"):result.rfind("}")+1]
                return json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("의도 분석 JSON 파싱 실패, 기본값 사용")
        
        # 파싱 실패 시 기본값
        return {
            "intent": user_input[:100],
            "required_tool": "market_flow",
            "params": {"query": user_input}
        }
    
    def finalize_report(self, worker_result: Dict[str, Any], 
                        principles: List[Dict[str, Any]], 
                        user_input: str) -> str:
        """최종 리포트 생성"""
        principles_text = "\n".join([
            f"- {p.get('content', '')}" 
            for p in principles
        ])
        
        # 워커 결과가 없는 경우 처리
        worker_text = "Worker에서 결과를 받지 못했습니다."
        if worker_result and not worker_result.get("error"):
            try:
                worker_text = json.dumps(worker_result, ensure_ascii=False, indent=2)
            except:
                worker_text = str(worker_result)
        
        system = """너는 투자 고문 역할을 해.
워커의 분석 결과와 저장된 투자 원칙을 결합하여,
사용자에게 명확하고 실행 가능한 투자 지혜를 제공해.
전문적이면서도 이해하기 쉽게 작성해."""
        
        user = f"""사용자 질문: {user_input}

워커 분석 결과:
{worker_text}

적용된 투자 원칙:
{principles_text}

최종 투자 리포트를 작성해줘."""
        
        return self.chat(system, user)


# ==================== ManagerCore ====================
class ManagerCore:
    """메니저 코어 - LangGraph 기반 워크플로우"""
    
    def __init__(self):
        self.llm = OllamaClient(model="gemma2:27b")
        self.memory = MemoryManager()
        self.worker_url = os.getenv("WORKER_URL", "http://localhost:8000")
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """LangGraph 빌드"""
        graph = StateGraph(AgentState)
        
        # 노드 추가
        graph.add_node("analyze_intent", self.analyze_intent_node)
        graph.add_node("call_worker", self.call_worker_node)
        graph.add_node("finalize_report", self.finalize_report_node)
        
        # 엣지 추가
        graph.set_entry_point("analyze_intent")
        graph.add_edge("analyze_intent", "call_worker")
        graph.add_edge("call_worker", "finalize_report")
        graph.add_edge("finalize_report", END)
        
        return graph.compile()
    
    # ==================== 노드 구현 (방어적) ====================
    async def analyze_intent_node(self, state: AgentState) -> AgentState:
        """
        analyze_intent: 사용자 의도 분석 + 관련 원칙 조회
        """
        user_input = state.get("user_input", "")
        user_id = state.get("user_id", "default")
        
        try:
            # 1. 관련 원칙 검색 (RAG)
            principles = self.memory.get_relevant_principles(
                query=user_input,
                n_results=5
            )
            
            # 2. LLM으로 의도 분석
            analysis = self.llm.analyze_intent(user_input, principles)
            
            state["selected_tool"] = analysis.get("required_tool", "market_flow")
            state["tool_params"] = analysis.get("params", {"query": user_input})
            state["applied_principles"] = principles
            
            logger.info(f"[analyze_intent] 도구: {state['selected_tool']}, 원칙: {len(principles)}개 적용")
            
        except Exception as e:
            logger.error(f"의도 분석 오류: {e}")
            state["error"] = f"의도 분석 실패: {str(e)}"
            state["selected_tool"] = "market_flow"
            state["tool_params"] = {"query": user_input}
            state["applied_principles"] = []
        
        return state
    
    async def call_worker_node(self, state: AgentState) -> AgentState:
        """
        call_worker: RTX Worker API 호출 (재시도 로직 포함)
        """
        import aiohttp
        
        tool_name = state.get("selected_tool", "market_flow")
        params = state.get("tool_params", {})
        task_id = f"task_{os.urandom(4).hex()}"
        
        last_error = None
        
        # 재시도 루프
        for attempt in range(Config.MAX_RETRIES):
            try:
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=Config.WORKER_TIMEOUT)
                ) as session:
                    payload = {
                        "tool_name": tool_name,
                        "params": params,
                        "task_id": task_id,
                        "summarize": True
                    }
                    
                    async with session.post(
                        f"{self.worker_url}/execute",
                        json=payload
                    ) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            state["worker_result"] = result.get("raw_result")
                            state["worker_summary"] = result.get("summary")
                            logger.info(f"[call_worker] 성공 (시도 {attempt + 1})")
                            return state
                        elif resp.status == 404:
                            state["error"] = f"도구를 찾을 수 없음: {tool_name}"
                            logger.error(f"[call_worker] 404: {tool_name}")
                            return state
                        else:
                            last_error = f"HTTP {resp.status}"
                            logger.warning(f"[call_worker] HTTP 오류: {resp.status}")
                            
            except aiohttp.ClientConnectorError as e:
                last_error = f"연결 실패: {str(e)}"
                logger.warning(f"[call_worker] 연결 실패 (시도 {attempt + 1}/{Config.MAX_RETRIES})")
            except asyncio.TimeoutError:
                last_error = "타임아웃"
                logger.warning(f"[call_worker] 타임아웃 (시도 {attempt + 1}/{Config.MAX_RETRIES})")
            except Exception as e:
                last_error = str(e)
                logger.error(f"[call_worker] 예외: {e}")
            
            # 재시도 전 대기
            if attempt < Config.MAX_RETRIES - 1:
                await asyncio.sleep(Config.RETRY_DELAY)
        
        # 모든 재시도 실패
        state["error"] = f"Worker 연결 실패: {last_error}"
        state["worker_result"] = {"error": last_error}
        logger.error(f"[call_worker] 최대 재시도 초과: {last_error}")
        
        return state
    
    async def finalize_report_node(self, state: AgentState) -> AgentState:
        """
        finalize_report: 워커 결과 + 원칙 → 최종 리포트
        """
        worker_result = state.get("worker_result", {})
        principles = state.get("applied_principles", [])
        user_input = state.get("user_input", "")
        
        try:
            # LLM으로 최종 리포트 생성
            final_report = self.llm.finalize_report(worker_result, principles, user_input)
            state["final_report"] = final_report
            
            # 작업 로그 저장
            self.memory.save_log(
                task_id=state.get("task_id", "unknown"),
                task_type="investment_analysis",
                status="completed",
                input_data={"user_input": user_input},
                result={
                    "tool": state.get("selected_tool"),
                    "principles_count": len(principles),
                    "report_length": len(final_report)
                }
            )
            
            logger.info(f"[finalize_report] 리포트 생성 완료 ({len(final_report)}자)")
            
        except Exception as e:
            logger.error(f"최종 리포트 생성 오류: {e}")
            state["final_report"] = f"분석 완료되었으나 리포트 생성 중 오류가 발생했습니다: {str(e)}"
        
        return state
    
    # ==================== 실행 ====================
    async def run(self, user_input: str, user_id: str = "default") -> Dict[str, Any]:
        """
        작업 실행
        
        Args:
            user_input: 사용자 질문
            user_id: 사용자 ID
        
        Returns:
            최종 결과 (리포트, 적용된 원칙, 워커 결과)
        """
        initial_state = AgentState(
            user_input=user_input,
            user_id=user_id,
            selected_tool=None,
            tool_params=None,
            worker_result=None,
            worker_summary=None,
            applied_principles=[],
            final_report=None,
            error=None
        )
        
        result = await self.graph.ainvoke(initial_state)
        
        return {
            "final_report": result.get("final_report"),
            "applied_principles": result.get("applied_principles"),
            "worker_result": result.get("worker_result"),
            "worker_summary": result.get("worker_summary"),
            "error": result.get("error")
        }


# ==================== 테스트 ====================
if __name__ == "__main__":
    async def main():
        manager = ManagerCore()
        
        # 테스트 실행
        result = await manager.run(
            user_input="현재 시장 상황에서 Tech 주식을-buy할까요?",
            user_id="user_001"
        )
        
        print("\n=== 최종 리포트 ===")
        print(result["final_report"])
        print("\n=== 적용된 원칙 ===")
        for p in result["applied_principles"]:
            print(f"- {p.get('content')}")
    
    asyncio.run(main())