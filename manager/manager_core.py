"""
Manager Core - MacBook에서 실행되는 LangGraph 메인 로직
Gemma-27B(Ollama)를 사용한 중앙 통제 시스템
방어적 코딩 적용: 네트워크 병목, 서버 다운 등 예외 상황 처리
"""
from typing import Dict, Any, List, Optional
from pathlib import Path
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
import asyncio
import os
import json
import logging
from shared.config_loader import NexusConfig

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# memory_manager import
from manager.memory_manager import MemoryManager


# ==================== 설정 로드 ====================
_CONFIG = NexusConfig.load_manifest()

# ==================== 설정 ====================
class Config:
    """설정"""
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    
    @property
    def WORKER_TIMEOUT(self):
        return NexusConfig.get_timeout("worker", 60)
    
    @property
    def OLLAMA_TIMEOUT(self):
        return NexusConfig.get_timeout("ollama", 60)
    
    @property
    def WORKER_URL(self):
        """Worker 서버의 URL을 동적으로 가져옵니다."""
        return os.getenv("WORKER_URL", NexusConfig.get_worker_url())

    @property
    def MANAGER_MODEL(self):
        return NexusConfig.get_model("manager")


# ==================== AgentState 정의 ====================
class AgentState(dict):
    """에이전트 상태"""
    # 사용자 입력
    user_input: str
    user_id: str
    
    # 선택된 도구
    selected_tool: Optional[str]
    tool_params: Optional[Dict[str, Any]]
    
    # 워커 결과 및 히스토리
    worker_result: Optional[Dict[str, Any]]
    worker_summary: Optional[str]
    research_history: List[Dict[str, Any]] # 추가: 여러 도구 실행 결과 저장
    
    # 제어 플래그
    is_finished: bool # 추가: 분석 완료 여부
    iteration_count: int # 추가: 무한 루프 방지
    
    # 적용된 원칙
    applied_principles: List[Dict[str, Any]]
    
    # 최종 리포트
    final_report: Optional[str]
    
    # 오류
    error: Optional[str]


# ==================== LLM 클라이언트 (방어적) ====================
class OllamaClient:
    """Ollama 클라이언트"""
    
    def __init__(self, model: str = None):
        # 인스턴스 생성 시점에 가장 최신 모델을 가져오거나 명시된 모델 사용
        self.model = model or NexusConfig.get_model("manager")
    
    def chat(self, system: str, user: str, timeout: int = None) -> str:
        """채팅 응답 생성"""
        import ollama
        actual_timeout = timeout or NexusConfig.get_timeout("ollama", 60)
        
        try:
            from ollama import Client
            client = Client(timeout=actual_timeout)
            response = client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ]
            )
            return response["message"]["content"]
        except Exception as e:
            logger.error(f"Ollama 오류: {e}")
            return f"AI 분석 중 오류가 발생했습니다: {str(e)[:100]}"
    
    def analyze_intent(self, user_input: str, principles: List[Dict[str, Any]], 
                       user_profile: Optional[Dict[str, Any]] = None,
                       research_history: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """의도 분석 (연구 히스토리 반영)"""
        principles_text = "\n".join([f"- {p.get('content', '')}" for p in principles]) if principles else "없음"
        
        # 도구 목록 구성
        skills = NexusConfig.load_manifest().get("tools", {}).get("skills", [])
        mcp_tools = NexusConfig.load_manifest().get("tools", {}).get("mcp", [])
        tools_text = "\n".join([f"- {t.get('name')}: {t.get('description')}" for t in skills + mcp_tools])
        
        # 연구 히스토리 요약
        history_text = "\n".join([
            f"[{h['tool']} 결과]: {h['summary'][:300]}..." 
            for h in (research_history or [])
        ]) if research_history else "없음 (연구 시작 단계)"

        profile_text = f"\n[사용자 성향]\n{user_profile['profile']}" if user_profile and user_profile.get("profile") else ""
        
        system = f"""너는 고도로 숙련된 AI 리서치 매니저야. 사용자의 질문을 해결하기 위해 필요한 정보를 단계별로 수집해.

[수집 가이드라인]
1. **입체적 분석**: 주식/시장 분석 시 반드시 시세(`kospi_kosdaq_stock_server`), 여론(`reddit_mcp_buddy`), 최신 뉴스(`mcp_chrome`) 등 다양한 도구를 조합해.
2. **반복 연구**: 현재까지 수집된 정보가 부족하다면 "is_finished": false로 설정하고 다른 도구를 추가 선택해.
3. **종료 조건**: 충분한 정보가 모였거나 더 이상 새로운 인사이트가 없다면 "is_finished": true로 설정해.

[사용 가능한 도구]
{tools_text}

[지금까지 조사된 내용]
{history_text}{profile_text}

JSON 응답 형식:
{{
    "intent": "현재 분석 상황",
    "required_tool": "다음에 호출할 도구 이름 (없으면 null)",
    "params": {{"query": "도구 파라미터"}},
    "is_finished": true_또는_false,
    "thought": "왜 이 조사가 더 필요한지 설명"
}}

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
                        user_input: str,
                        user_profile: Optional[Dict[str, Any]] = None) -> str:
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
        
        profile_text = ""
        if user_profile and user_profile.get("profile"):
            profile_text = f"\n\n[중요: 사용자 성향/피드백 반영]\n다음은 사용자의 선호도 및 이전 피드백입니다:\n{user_profile['profile']}\n이 성향을 반드시 최우선으로 반영하여 리포트의 형식, 강조점, 어조를 최적화해."
        
        system = f"""너는 Nexus 시스템을 총괄하는 다목적 AI 매니저 및 아키텍트야.
사용자에게 명확하고 실행 가능한 답변을 제공하되, 결론을 내기 전 반드시 세 가지 상반된 시각(낙관, 비관, 중립)에서 검토하고 그 이면의 구조적 결함이 없는지 확인하여 리포트를 작성해.
워커의 분석/작업 결과와 저장된 원칙을 결합하여 분석을 수행해.
작업이 코드 수정이나 시스템 업데이트인 경우, 변경된 사항과 성공 여부를 명확히 요약해줘. 전문적이면서도 이해하기 쉽게 작성해.{profile_text}"""
        
        user = f"""사용자 질문: {user_input}

워커 분석 결과:
{worker_text}

적용된 원칙:
{principles_text}

최종 응답(리포트 또는 작업 결과 요약)을 작성해줘."""
        
        return self.chat(system, user)


# ==================== ManagerCore ====================
class ManagerCore:
    """메니저 코어 - LangGraph 기반 워크플로우"""
    
    def __init__(self):
        self.config = Config() # 인스턴스 생성하여 다이나믹 설정 지원
        self.memory = MemoryManager()
        self.graph = self._build_graph()

    @property
    def llm(self):
        """매니페스트 모델 설정을 실시간으로 반영하는 LLM 클라이언트"""
        return OllamaClient(model=self.config.MANAGER_MODEL)

    @property
    def worker_url(self):
        """동적으로 계산된 워커 URL"""
        return self.config.WORKER_URL
    
    def _build_graph(self) -> StateGraph:
        """LangGraph 빌드 (반복적 연구 루프 포함)"""
        graph = StateGraph(AgentState)
        
        # 노드 추가
        graph.add_node("analyze_intent", self.analyze_intent_node)
        graph.add_node("call_worker", self.call_worker_node)
        graph.add_node("finalize_report", self.finalize_report_node)
        
        # 엣지 추가 (조건부 루프)
        graph.set_entry_point("analyze_intent")
        
        # analyze_intent 이후: 완료되었으면 리포트로, 아니면 워커 호출로
        graph.add_conditional_edges(
            "analyze_intent",
            self._should_continue_research,
            {
                "continue": "call_worker",
                "finish": "finalize_report"
            }
        )
        
        # call_worker 이후: 다시 analyze_intent로 돌아가서 추가 작업 판단
        graph.add_edge("call_worker", "analyze_intent")
        
        graph.add_edge("finalize_report", END)
        
        return graph.compile()

    def _should_continue_research(self, state: AgentState) -> str:
        """연구를 계속할지 판단하는 라우터"""
        if state.get("is_finished") or state.get("iteration_count", 0) >= 3:
            return "finish"
        if state.get("selected_tool"):
            return "continue"
        return "finish"
    
    # ==================== 노드 구현 (방어적) ====================
    async def analyze_intent_node(self, state: AgentState) -> AgentState:
        """
        analyze_intent: 사용자 의도 분석 + 관련 원칙 조회
        """
        user_input = state.get("user_input", "")
        user_id = state.get("user_id", "default")
        research_history = state.get("research_history", [])
        iteration_count = state.get("iteration_count", 0)
        
        state["iteration_count"] = iteration_count + 1
        
        try:
            # 1. 관련 원칙 및 사용자 성향 조회
            principles = self.memory.get_relevant_principles(query=user_input, n_results=5)
            user_profile = self.memory.get_user_profile(user_id)
            
            # [First Principles] 시스템 제1원리 강제 적용
            first_principle = {"content": "모든 현상을 이원성의 균형 속에서 파악하고, 본질적인 구조와 흐름을 먼저 분석하라"}
            if not any(p.get("content") == first_principle["content"] for p in principles):
                principles.insert(0, first_principle)
            
            state["applied_principles"] = principles
            
            # 2. LLM 의도 분석 (히스토리 포함)
            result = self.llm.analyze_intent(user_input, principles, user_profile, research_history)
            
            state["selected_tool"] = result.get("required_tool")
            state["tool_params"] = result.get("params", {})
            state["is_finished"] = result.get("is_finished", False)
            
            if state["selected_tool"]:
                logger.info(f"[{state['iteration_count']}/3] 도구 선택: {state['selected_tool']}, 생각: {result.get('thought')}")
            
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
        for attempt in range(self.config.MAX_RETRIES):
            try:
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=self.config.WORKER_TIMEOUT)
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
                            raw_result = result.get("raw_result")
                            summary = result.get("summary", "요약 없음")
                            
                            state["worker_result"] = raw_result
                            state["worker_summary"] = summary
                            
                            # 히스토리에 추가
                            if "research_history" not in state:
                                state["research_history"] = []
                            
                            state["research_history"].append({
                                "tool": tool_name,
                                "params": params,
                                "result": raw_result,
                                "summary": summary
                            })
                            
                            logger.info(f"[call_worker] {tool_name} 성공 (시도 {attempt + 1})")
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
                logger.warning(f"[call_worker] 연결 실패 (시도 {attempt + 1}/{self.config.MAX_RETRIES})")
            except asyncio.TimeoutError:
                last_error = "타임아웃"
                logger.warning(f"[call_worker] 타임아웃 (시도 {attempt + 1}/{self.config.MAX_RETRIES})")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"[call_worker] 알 수 없는 오류 (시도 {attempt + 1}/{self.config.MAX_RETRIES}): {e}")
            
            # 재시도 전 대기
            if attempt < self.config.MAX_RETRIES - 1:
                await asyncio.sleep(self.config.RETRY_DELAY)
        
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
        user_id = state.get("user_id", "default")
        
        try:
            # 사용자 성향 조회
            user_profile = self.memory.get_user_profile(user_id)
            research_history = state.get("research_history", [])
            
            # LLM으로 최종 리포트 생성 (히스토리 전체 반영)
            final_report = self.llm.finalize_report(worker_result, principles, user_input, user_profile)
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
    async def run(self, user_input: str, user_id: str = "default", is_autonomous: bool = False) -> Dict[str, Any]:
        """
        작업 실행
        
        Args:
            user_input: 사용자 질문
            user_id: 사용자 ID
            is_autonomous: 자율 모드 여부
        
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
        
        if is_autonomous:
            if result.get("final_report"):
                self.memory.save_autonomous_log(result.get("final_report"))
        else:
            # [Evolving Agent] 세션 종료 후 비동기로 성찰(Reflection) 수행
            asyncio.create_task(self.self_reflection(result))
        
        return {
            "final_report": result.get("final_report"),
            "applied_principles": result.get("applied_principles"),
            "worker_result": result.get("worker_result"),
            "worker_summary": result.get("worker_summary"),
            "error": result.get("error")
        }


    def process_feedback(self, user_id: str, task_id: str, feedback_text: str) -> bool:
        """
        사용자 피드백을 분석하여 성향을 업데이트하는 Self-Reflection Loop
        """
        try:
            logger.info(f"피드백 처리 시작 - User: {user_id}")
            
            # 1. 피드백 저장
            self.memory.save_feedback(task_id, "preference", feedback_text, rating=None)
            
            # 2. 기존 사용자 성향 조회
            current_profile = self.memory.get_user_profile(user_id)
            current_text = current_profile.get("profile", "초기 설정된 성향이 없습니다.") if current_profile else "초기 설정된 성향이 없습니다."
            
            # 3. LLM을 통한 성향 업데이트 (Self-Reflection)
            system_prompt = """너는 사용자의 피드백을 분석하여 투자 성향 프로필을 지속적으로 최적화하는 '성향 분석가'야.
기존 프로필과 새로운 피드백을 바탕으로, 앞으로 AI 에이전트가 어떤 도구를 우선적으로 선택하고 어떤 형식(포맷, 어조, 초점)으로 리포트를 작성해야 할지 지침을 만들어줘.
최종 결과물은 다음 에이전트가 프롬프트로 바로 사용할 수 있도록 간결하고 명확한 지시문 형태로 작성해야 해."""
            
            user_prompt = f"""[기존 프로필]
{current_text}

[새로운 피드백]
{feedback_text}

위 피드백을 반영하여 사용자 프로필 지시문을 업데이트해줘."""
            
            updated_profile_text = self.llm.chat(system_prompt, user_prompt)
            
            # 4. 새로운 성향 저장
            success = self.memory.save_user_profile(user_id, updated_profile_text)
            if success:
                logger.info(f"사용자 성향 업데이트 완료:\n{updated_profile_text}")
            return success
            
        except Exception as e:
            logger.error(f"피드백 처리 중 오류 발생: {e}")
            return False

    async def self_reflection(self, state: AgentState):
        """세션 종료 후 에이전트 스스로의 학습(Reflection) 수행"""
        user_input = state.get("user_input", "")
        final_report = state.get("final_report", "")
        if not final_report: return
        
        system_prompt = "너는 자신의 분석을 비판적으로 검토하고 사용자의 의도를 깊이 이해하여 학습하는 '자아성찰 에이전트'야."
        user_prompt = f"""
최근 대화 내용:
사용자 질문: {user_input}
에이전트 답변: {final_report[:1000]}...

위 대화에서 에이전트가 앞으로의 분석을 위해 '배운 점' 또는 '사용자 취향'을 한 문장으로 요약해줘.
예: "사용자는 거시 경제보다 개별 기업의 재무 건전성에 더 높은 비중을 둡니다."
중요: 사용자가 구체적으로 지적한 사항이나 선호가 보일 때만 작성하고, 내용이 뻔하거나 학습할 점이 없다면 '없음'이라고 답해줘.
"""
        try:
            # 성찰을 위한 LLM 호출 (타임아웃 30초)
            reflection = self.llm.chat(system_prompt, user_prompt, timeout=30)
            if reflection and "없음" not in reflection:
                self.memory.save_learning(reflection)
                logger.info(f"[Evolving Agent] 새로운 학습 내용 저장: {reflection}")
        except Exception as e:
            logger.error(f"성찰 도중 오류: {e}")


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