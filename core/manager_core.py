"""
Manager Core - MacBook에서 실행되는 LangGraph 메인 로직
통합 실행 모델: 모든 스킬은 로컬에서 실행, LLM 요청만 분산 처리
방어적 코딩 적용
"""
from typing import Dict, Any, List, Optional
import asyncio
import os
import json
import logging
import aiohttp
from langgraph.graph import StateGraph, END
from core.config_loader import NexusConfig
from core.memory_manager import MemoryManager

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== 설정 ====================
class Config:
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
        return os.getenv("WORKER_URL", NexusConfig.get_worker_url())

    @property
    def MANAGER_MODEL(self):
        return NexusConfig.get_model("manager")

    @property
    def WORKER_MODEL(self):
        return NexusConfig.get_model("worker")

# ==================== AgentState 정의 ====================
class AgentState(dict):
    user_input: str
    user_id: str
    selected_tool: Optional[str]
    selected_model: Optional[str]
    tool_params: Optional[Dict[str, Any]]
    worker_result: Optional[Dict[str, Any]]
    worker_summary: Optional[str]
    research_history: List[Dict[str, Any]]
    is_finished: bool
    iteration_count: int
    applied_principles: List[Dict[str, Any]]
    final_report: Optional[str]
    error: Optional[str]

# ==================== LLM 클라이언트 (분산형) ====================
class OllamaClient:
    """Ollama 클라이언트 - 로컬(Server)과 원격(Worker) 요청 지원"""
    
    def __init__(self, model: str = None, remote_url: str = None):
        self.local_model = model or NexusConfig.get_model("manager")
        self.remote_model = NexusConfig.get_model("worker")
        self.remote_url = remote_url or NexusConfig.get_worker_url()
        self.worker_available = True # 기본값은 가용한 것으로 가정
    
    async def check_health(self) -> bool:
        """원격 워커 연결 상태를 확인합니다."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(f"{self.remote_url}/api/tags") as resp:
                    self.worker_available = (resp.status == 200)
                    return self.worker_available
        except:
            self.worker_available = False
            return False

    async def chat(self, system: str, user: str, use_remote: bool = False, timeout: int = None, model: str = None) -> str:
        """채팅 응답 생성 (Fast tasks use remote worker, Deep tasks use local manager)"""
        actual_timeout = timeout or NexusConfig.get_timeout("ollama", 120)
        
        # 워커가 가용하지 않다면 무조건 로컬 사용
        if use_remote and not self.worker_available:
            logger.info("📡 Worker offline, forcing local fallback.")
            use_remote = False
            
        if use_remote:
            return await self._chat_remote(system, user, actual_timeout, model=model)
        else:
            return self._chat_local(system, user, actual_timeout, model=model)

    def _chat_local(self, system: str, user: str, timeout: int, model: str = None) -> str:
        """Local LLM 호출 (ollama library)"""
        import ollama
        try:
            target_model = model or self.local_model
            logger.info(f"🏠 [Local LLM] 대화 시작... (Model: {target_model})")
            resp = ollama.chat(
                model=target_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                options={"num_predict": 4096}
            )
            content = resp['message']['content']
            logger.info(f"--- [Local Response] ---\n{content[:200]}..." if len(content) > 200 else f"--- [Local Response] ---\n{content}")
            return content
        except Exception as e:
            logger.error(f"Local Ollama 오류: {e}")
            return f"로컬 AI 분석 중 오류: {str(e)[:100]}"

    async def _chat_remote(self, system: str, user: str, timeout: int, model: str = None) -> str:
        """원격 Worker(PC)의 Ollama API를 직접 호출 (Fast Tasks)"""
        target_model = model or self.remote_model
        logger.info(f"⚡ [Remote Ollama] Calling worker at {self.remote_url} (Model: {target_model})...")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                payload = {
                    "model": target_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user}
                    ],
                    "stream": False  # Ollama API 직접 호출 시 필수
                }
                # Ollama 기본 endpoint: /api/chat
                async with session.post(f"{self.remote_url}/api/chat", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data["message"]["content"]
                        logger.info(f"--- [LLM Response] ---\n{content[:200]}..." if len(content) > 200 else f"--- [LLM Response] ---\n{content}")
                        return content
                    else:
                        error_text = await resp.text()
                        logger.warning(f"Remote LLM failed ({resp.status}): {error_text}. Falling back to local.")
                        return self._chat_local(system, user, timeout)
        except Exception as e:
            logger.error(f"Remote LLM connection error: {e}. Falling back to local.")
            return self._chat_local(system, user, timeout)

    async def summarize_result(self, raw_result: Dict[str, Any], model: str = None) -> str:
        """작업 결과를 요약 (Fast task -> Remote)"""
        system = "너는 작업 실행 결과를 핵심만 요약하는 비서야."
        user = f"다음 결과를 요약해줘:\n{json.dumps(raw_result, ensure_ascii=False, indent=2)}"
        return await self.chat(system, user, use_remote=True, model=model)
    
    async def analyze_intent(self, user_input: str, principles: List[Dict[str, Any]], 
                       user_profile: Optional[Dict[str, Any]] = None,
                       research_history: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """의도 분석 (Fast task -> Remote)"""
        principles_text = "\n".join([f"- {p.get('content', '')}" for p in principles]) if principles else "없음"
        skills = NexusConfig.get_discovered_skills()
        mcp_tools = NexusConfig.load_manifest().get("tools", {}).get("mcp", [])
        tools_text = "\n".join([f"- {t.get('name')}: {t.get('description')}" for t in skills + mcp_tools])
        
        history_text = "\n".join([
            f"[{h['tool']} 결과]: {h['summary'][:300]}..." 
            for h in (research_history or [])
        ]) if research_history else "없음 (연구 시작 단계)"

        profile_text = f"\n[사용자 성향]\n{user_profile['profile']}" if user_profile and user_profile.get("profile") else ""
        
        system = f"""너는 고도로 숙련된 AI 리서치 매니저야. 사용자의 질문을 해결하기 위해 필요한 정보를 단계별로 수집해.
[수집 가이드라인]
1. 입체적 분석: 다양한 도구를 조합하여 시세, 여론, 뉴스를 모두 확인해.
2. 반복 연구: 정보가 부족하면 is_finished: false로 추가 검색을 수행해.
3. 종료 조건: 충분한 근거 데이터가 확보되었을 때만 is_finished: true로 설정해.

[사용 가능한 도구]
{tools_text}

[지금까지 조사된 내용]
{history_text}{profile_text}

JSON 응답 형식:
{{
    "intent": "현재 분석 상황",
    "required_tool": "다음에 호출할 도구 이름 (없으면 null)",
    "required_model": "사용할 모델 이름 (예: gemma2:9b, llama3.1 등)",
    "params": {{"query": "파라미터"}},
    "is_finished": true_또는_false,
    "thought": "상세 분석 계획"
}}
적용 가능한 원칙:
{principles_text}"""
        
        user = f"사용자 질문: {user_input}\n위 질문을 분석하여 JSON 형식으로 응답해줘."
        
        logger.info(f"🔍 [Thinking] 의도 분석 중... (Input: {user_input[:50]}...)")
        result_text = await self.chat(system, user, use_remote=True)
        
        try:
            if "{" in result_text and "}" in result_text:
                json_str = result_text[result_text.find("{"):result_text.rfind("}")+1]
                analysis = json.loads(json_str)
                
                # AI의 '생각'을 터미널에 출력
                thought = analysis.get("thought", "생각 중...")
                tool = analysis.get("required_tool", "None")
                model = analysis.get("required_model", "Default")
                logger.info(f"💭 [AI Thought]: {thought}")
                logger.info(f"🎯 [Next Action]: {tool} (Model: {model})")
                
                return analysis
        except:
            logger.warning("의도 분석 JSON 파싱 실패")
        
        return {"intent": user_input[:50], "required_tool": "web_researcher", "params": {"query": user_input}, "is_finished": False}
    
    async def finalize_report(self, worker_result: Dict[str, Any], 
                        principles: List[Dict[str, Any]], 
                        user_input: str,
                        user_profile: Optional[Dict[str, Any]] = None) -> str:
        """최종 리포트 생성 (Deep reasoning -> Local)"""
        principles_text = "\n".join([f"- {p.get('content', '')}" for p in principles])
        worker_text = json.dumps(worker_result, ensure_ascii=False, indent=2) if worker_result else "결과 없음"
        profile_text = f"\n\n[사용자 성향 반영]\n{user_profile['profile']}" if user_profile and user_profile.get("profile") else ""
        
        system = f"""너는 Nexus 시스템의 시니어 아키텍트이자 투자 분석가야. 
결론을 내기 전 반드시 낙관, 비관, 중립의 시각에서 검토하고 구조적 결함을 확인해 리포트를 작성해.
반드시 한국어로 전문적이면서도 실행 가능한 인사이트를 제공해.{profile_text}"""
        
        user = f"사용자 질문: {user_input}\n\n데이터 결과:\n{worker_text}\n\n적용 원칙:\n{principles_text}"
        
        return await self.chat(system, user, use_remote=False)

# ==================== ManagerCore ====================
class ManagerCore:
    """메니저 코어 - 모든 실행은 로컬에서, LLM만 분산"""
    
    def __init__(self, local_mode: bool = True):
        self.config = Config()
        self.memory = MemoryManager()
        self.llm = OllamaClient(remote_url=self.config.WORKER_URL)
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(AgentState)
        graph.add_node("analyze_intent", self.analyze_intent_node)
        graph.add_node("execute_tool", self.execute_tool_node)
        graph.add_node("finalize_report", self.finalize_report_node)
        
        graph.set_entry_point("analyze_intent")
        graph.add_conditional_edges(
            "analyze_intent",
            self._should_continue_research,
            {"continue": "execute_tool", "finish": "finalize_report"}
        )
        graph.add_edge("execute_tool", "analyze_intent")
        graph.add_edge("finalize_report", END)
        return graph.compile()

    def _should_continue_research(self, state: AgentState) -> str:
        if state.get("is_finished") or state.get("iteration_count", 0) >= 5:
            return "finish"
        if state.get("selected_tool"):
            return "continue"
        return "finish"
    
    async def analyze_intent_node(self, state: AgentState) -> AgentState:
        user_input = state.get("user_input", "")
        user_id = state.get("user_id", "default")
        research_history = state.get("research_history", [])
        state["iteration_count"] = state.get("iteration_count", 0) + 1
        
        principles = self.memory.get_relevant_principles(query=user_input, n_results=5)
        user_profile = self.memory.get_user_profile(user_id)
        state["applied_principles"] = principles
        
        result = await self.llm.analyze_intent(user_input, principles, user_profile, research_history)
        state["selected_tool"] = result.get("required_tool")
        state["selected_model"] = result.get("required_model")
        state["tool_params"] = result.get("params", {})
        state["is_finished"] = result.get("is_finished", False)
        
        return state
    
    async def execute_tool_node(self, state: AgentState) -> AgentState:
        """모든 도구를 서버 로컬에서 직접 실행"""
        tool_name = state.get("selected_tool")
        selected_model = state.get("selected_model")
        params = state.get("tool_params", {})
        
        # 도구 이름이 리스트로 들어오는 경우 방어 로직
        if isinstance(tool_name, list) and len(tool_name) > 0:
            tool_name = tool_name[0]
        
        if not tool_name: return state

        logger.info(f"🛠️ Executing tool locally: {tool_name}")
        try:
            raw_result = self._execute_locally(tool_name, params)
            # 결과 요약 시 AI가 선택한 모델 사용
            summary = await self.llm.summarize_result(raw_result, model=selected_model)
            
            state["worker_result"] = raw_result
            state["worker_summary"] = summary
            
            if "research_history" not in state:
                state["research_history"] = []
            state["research_history"].append({
                "tool": tool_name, "params": params, "result": raw_result, "summary": summary
            })
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            state["error"] = str(e)
            state["is_finished"] = True
            
        return state

    def _execute_locally(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        import importlib
        module_name = f"skills.{tool_name}"
        module = importlib.import_module(module_name)
        if hasattr(module, "run"):
            return module.run(params)
        raise AttributeError(f"Module {module_name} has no 'run'")
    
    async def finalize_report_node(self, state: AgentState) -> AgentState:
        user_input = state.get("user_input", "")
        user_id = state.get("user_id", "default")
        worker_result = state.get("worker_result", {})
        principles = state.get("applied_principles", [])
        user_profile = self.memory.get_user_profile(user_id)
        
        final_report = await self.llm.finalize_report(worker_result, principles, user_input, user_profile)
        state["final_report"] = final_report
        return state
    
    async def run(self, user_input: str, user_id: str = "default", is_autonomous: bool = False) -> Dict[str, Any]:
        initial_state = AgentState(
            user_input=user_input, user_id=user_id, research_history=[],
            iteration_count=0, applied_principles=[], is_finished=False
        )
        result = await self.graph.ainvoke(initial_state)
        return {
            "final_report": result.get("final_report"),
            "applied_principles": result.get("applied_principles"),
            "worker_result": result.get("worker_result"),
            "error": result.get("error")
        }

    def process_feedback(self, user_id: str, task_id: str, feedback_text: str) -> bool:
        # Simplified feedback for brevity, can be fully implemented if needed
        return True