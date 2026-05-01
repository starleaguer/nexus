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
from core.model_selector import ModelAvailabilityService
from shared.logger_utils import LLMLogger
from shared.utils import extract_json_from_text

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
    current_model_info: Optional[Dict[str, Any]]
    api_status: Optional[Dict[str, bool]]
    persona: Optional[str]
    strategy: Optional[str]

# ==================== LLM 클라이언트 (분산형) ====================
class OllamaClient:
    """Ollama 클라이언트 - 로컬(Server)과 원격(Worker) 요청 지원"""
    
    def __init__(self, model: str = None, remote_url: str = None):
        self.local_model = model or NexusConfig.get_model("manager")
        self.remote_model = NexusConfig.get_model("worker")
        self.remote_url = remote_url or NexusConfig.get_worker_url()
        self.worker_available = True 
        # 동시 다발적 요청으로 인한 LLM 서버(로컬/워커) 과부하 방지를 위한 세마포어
        self._semaphore = asyncio.BoundedSemaphore(3)
    
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

    async def chat(self, system: str, user: str, use_remote: bool = False, timeout: int = None, model: str = None, step: str = "General") -> str:
        """채팅 응답 생성 (Fast tasks use remote worker, Deep tasks use local manager)"""
        actual_timeout = timeout or NexusConfig.get_timeout("ollama", 300)
        
        assigned_model = model or (self.remote_model if use_remote else self.local_model)
        tier = "Unknown"
        if "gemini" in assigned_model.lower(): tier = "Tier 1 (Cloud)"
        elif "llama-3.3" in assigned_model.lower(): tier = "Tier 3 (Groq/Cloud)"
        elif "groq" in assigned_model.lower(): tier = "Tier 1 (Speed)"
        elif use_remote: tier = "Tier 2 (Worker)"
        else: tier = "Tier 3 (Local)"

        if use_remote and not self.worker_available:
            logger.info("📡 Worker offline, forcing local fallback.")
            use_remote = False
            tier = "Tier 3 (Fallback)"
            
        async with self._semaphore:
            try:
                prompt = f"System: {system}\nUser: {user}"
                if model and ("gemini" in model.lower()):
                    result = await self._chat_gemini(system, user, actual_timeout, model=model)
                elif model and ("llama-3" in model.lower() or "mixtral" in model.lower()):
                    result = await self._chat_groq(system, user, actual_timeout, model=model)
                elif use_remote:
                    result = await self._chat_remote(system, user, actual_timeout, model=model)
                else:
                    result = await self._chat_local(system, user, actual_timeout, model=model)

                # 로그 파일에 기록
                LLMLogger.log_interaction(tier, assigned_model, step, prompt, result)

                if not isinstance(result, str):
                    logger.error(f"⚠️ [chat] Expected string result, got {type(result)}: {result}")
                    result = str(result)

                error_indicators = ["Error:", "API 오류", "연결 오류", "인증 실패", "MLX 서버 오류", "MLX 연결 오류", "RESOURCE_EXHAUSTED", "429"]
                if any(ind in result for ind in error_indicators):
                    # Gemini가 이미 실패한 경우라면 다른 티어로 폴백
                    if "gemini" in assigned_model.lower():
                        logger.warning(f"⚠️ Gemini 실행 실패 ({result[:60]})... Groq로 우회.")
                        groq_result = await self._chat_groq(system, user, actual_timeout)
                        
                        # [추가] Groq 폴백 결과 기록 (Llama 3.3은 Tier 3급 성능)
                        LLMLogger.log_interaction("Tier 3 (Fallback)", "llama-3.3-70b-versatile", f"{step} (Groq Fallback)", prompt, groq_result)
                        
                        if not any(ind in groq_result for ind in error_indicators):
                            return groq_result
                        
                        logger.warning(f"⚠️ Groq도 실패. Local로 최종 우회.")
                        local_result = await self._chat_local(system, user, actual_timeout)
                        
                        # [추가] Local 폴백 결과 기록
                        LLMLogger.log_interaction("Tier 3 (Fallback)", "Local Manager", f"{step} (Local Fallback)", prompt, local_result)
                        
                        return local_result
                    
                    # Gemini가 아닌 모델이 실패한 경우 Gemini로 우회 시도
                    logger.warning(f"⚠️ 모델 실행 실패 ({assigned_model}): {result[:60]}... Gemini로 우회.")
                    gemini_result = await self._chat_gemini(system, user, actual_timeout)
                    
                    # [추가] Gemini 우회 결과 기록
                    LLMLogger.log_interaction("Tier 1 (Fallback)", "Gemini Flash", f"{step} (Gemini Fallback)", prompt, gemini_result)
                    
                    return gemini_result

                return result

            except Exception as e:
                logger.error(f"🚨 모델 실행 중 예외: {e} | Type: {type(e)}", exc_info=True)
                # 예외 발생 시 안전한 순차 폴백 및 로그 기록
                if model and "gemini" in model.lower():
                    fallback_result = await self._chat_groq(system, user, actual_timeout)
                    LLMLogger.log_interaction("Tier 1 (Fallback-EX)", "Groq", f"{step} (Exception Fallback)", prompt, fallback_result)
                    return fallback_result
                
                fallback_result = await self._chat_gemini(system, user, actual_timeout)
                LLMLogger.log_interaction("Tier 1 (Fallback-EX)", "Gemini", f"{step} (Exception Fallback)", prompt, fallback_result)
                return fallback_result

    async def _chat_gemini(self, system: str, user: str, timeout: int, model: str = None) -> str:
        """Google Gemini API 호출 (Flash → Flash-Lite 자동 폴백)"""
        from google import genai
        from google.genai import types
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key: return "Error: GEMINI_API_KEY missing"
        
        client = genai.Client(api_key=api_key)
        
        # 최신 권장 모델인 flash-lite-latest를 1순위로 설정
        models_to_try = [model or "models/gemini-flash-lite-latest"]
        
        # 기본 모델이 flash-lite라면 더 높은 지능의 flash 및 pro 모델을 폴백으로 추가
        if "flash-lite" in models_to_try[0]:
            models_to_try.extend(["models/gemini-flash-latest", "models/gemini-pro-latest"])
        elif "gemini" in models_to_try[0] and "models/" not in models_to_try[0]:
            # 접두사가 없는 경우를 대비한 보정
            models_to_try[0] = f"models/{models_to_try[0]}"
        
        last_error = None
        for target_model in models_to_try:
            try:
                logger.info(f"✨ [Gemini API] Generating... ({target_model})")
                response = client.models.generate_content(
                    model=target_model,
                    contents=user,
                    config=types.GenerateContentConfig(system_instruction=system)
                )
                
                # SDK 에러 방지를 위해 .text 대신 candidates 직접 검증
                if response.candidates and len(response.candidates) > 0:
                    cand = response.candidates[0]
                    # 콘텐트 파트가 존재하는지 확인
                    if cand.content and cand.content.parts:
                        text = "".join([part.text for part in cand.content.parts if part.text])
                        if text.strip():
                            return text
                
                logger.warning(f"⚠️ [Gemini] {target_model} 유효한 텍스트 응답 없음. 다음 모델 시도...")
                continue

            except Exception as e:
                err_str = str(e).lower()
                last_error = e
                
                # 재시도 가능한 에러 패턴 (429 할당량 초과 포함)
                retryable_errors = ["429", "resource_exhausted", "503", "unavailable", "overloaded", "empty", "must contain", "output error", "not found"]
                if any(err in err_str for err in retryable_errors):
                    logger.warning(f"⚠️ [Gemini] {target_model} 일시적 오류 ({err_str[:50]}) → 폴백 시도")
                    continue
                
                # 치명적 에러는 즉시 보고
                logger.error(f"🚨 Gemini API Critical Error ({target_model}): {e}")
                return f"Gemini API 오류: {str(e)}"
        
        logger.error(f"Gemini API 모든 모델 실패: {last_error}")
        return f"Gemini API 오류: {str(last_error)}"

    async def _chat_groq(self, system: str, user: str, timeout: int, model: str = None) -> str:
        """Groq Cloud API 호출"""
        target_model = model or "llama-3.3-70b-versatile"
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key: return "Error: GROQ_API_KEY missing"
        
        logger.info(f"⚡ [Groq API] Generating... ({target_model})")
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": target_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2
        }
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"]
                    return f"Groq API 오류 ({resp.status})"
        except Exception as e:
            return f"Groq 연결 오류: {str(e)}"

    async def _chat_local(self, system: str, user: str, timeout: int, model: str = None) -> str:
        """Tier 3 - MLX-LM 서버 호출 (OpenAI 호환 /v1/chat/completions)"""
        manifest = NexusConfig.load_manifest()
        local_cfg   = manifest.get("local", {})
        mlx_url     = local_cfg.get("url", "http://localhost:8080")
        target_model = model or local_cfg.get("model", self.local_model)

        logger.info(f"🧠 [MLX Local] 추론 시작... ({target_model})")
        try:
            payload = {
                "model": target_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user}
                ],
                "temperature": 0.2,
                "max_tokens": 2048,
                "stream": False,
            }
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                async with session.post(
                    f"{mlx_url}/v1/chat/completions", json=payload
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        try:
                            # OpenAI 호환 및 Thinking 모델(reasoning) 지원 파싱
                            msg = data["choices"][0]["message"]
                            content = msg.get("content") or ""
                            reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
                            
                            # 두 필드 중 하나라도 있으면 결합하여 반환
                            final_text = ""
                            if reasoning:
                                final_text += f"[Reasoning]\n{reasoning}\n\n"
                            if content:
                                final_text += content
                                
                            if final_text.strip():
                                return final_text
                            else:
                                logger.error(f"⚠️ [MLX] 응답에 유효한 텍스트가 없음: {data}")
                                return "MLX 응답 오류: 빈 내용"
                        except (KeyError, IndexError) as e:
                            logger.error(f"🚨 [MLX] 응답 파싱 실패: {e} | Data: {data}")
                            return f"MLX 파싱 오류: {str(e)}"
                    
                    err = await resp.text()
                    logger.error(f"MLX 서버 오류 ({resp.status}): {err[:100]}")
                    return f"MLX 서버 오류: HTTP {resp.status}"
        except asyncio.TimeoutError:
            return f"MLX 서버 타임아웃 ({timeout}s 초과)"
        except Exception as e:
            return f"MLX 연결 오류: {str(e)[:80]}"


    async def _chat_remote(self, system: str, user: str, timeout: int, model: str = None) -> str:
        """원격 Worker(PC)의 Ollama API 호출"""
        target_model = model or self.remote_model
        logger.info(f"⚡ [Remote Ollama] Calling worker... ({target_model})")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                payload = {
                    "model": target_model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "stream": False
                }
                async with session.post(f"{self.remote_url}/api/chat", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["message"]["content"]
                    return await self._chat_local(system, user, timeout)
        except:
            return await self._chat_local(system, user, timeout)

    async def summarize_result(self, raw_result: Dict[str, Any], model: str = None) -> str:
        """작업 결과를 요약"""
        system = "너는 작업 실행 결과를 핵심만 요약하는 비서야."
        user = f"다음 결과를 요약해줘:\n{json.dumps(raw_result, ensure_ascii=False, indent=2)}"
        return await self.chat(system, user, use_remote=True, model=model, step="Result Summarization")
    
    async def analyze_intent(self, user_input: str, principles: List[Dict[str, Any]], 
                       user_profile: Optional[Dict[str, Any]] = None,
                       research_history: List[Dict[str, Any]] = None,
                       model_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """의도 분석 및 전략 수립 (Autonomous Planning & Persona)"""
        
        # 1. 원칙 주입
        principles_text = "\n".join([f"- {p.get('content', '')}" for p in principles])
        
        # 2. 도구 목록 (전체 제공)
        all_skills = NexusConfig.get_discovered_skills()
        mcp_tools = NexusConfig.load_manifest().get("tools", {}).get("mcp", [])
        all_tools = all_skills + mcp_tools
        
        def distill_description(desc: str) -> str:
            if not desc: return ""
            lines = [line.strip() for line in desc.split('\n') if line.strip()]
            if not lines: return ""
            summary = lines[0]
            context = [line for line in lines[1:] if line.startswith("[사용 시점]") or line.startswith("[출력]")]
            return f"{summary} {' '.join(context)}".strip()

        tools_text = "\n".join([f"- {t.get('name')}: {distill_description(t.get('description'))}" for t in all_tools])
        
        # 3. 컨텍스트 및 히스토리
        history_text = "\n".join([f"[{h['tool']} 결과]: {h['summary'][:1500]}..." for h in (research_history or [])])
        profile_text = f"\n[사용자 성향 및 배경]\n{user_profile['profile']}" if user_profile and user_profile.get("profile") else ""
        
        system = f"""너는 Nexus 시스템의 지능형 오케스트레이터야. 
[자율 운영 원칙]
1. 고정된 페르소나 대신, 사용자 질문에 가장 적합한 '전문가 페르소나'를 스스로 정의하여 응답해.
2. 질문의 복잡도와 필요한 데이터의 종류를 고려하여 '분석 전략(Strategy)'을 수립해.
3. [Active Workspace]에 답변을 위한 실제 데이터가 없다면 절대로 추측하지 말고 적절한 도구를 선택해. (특히 주식 시세 등 실시간 정보 필수)
4. 이미 답변 가능한 충분한 정보가 수집된 경우에만 'is_finished'를 true로 설정해.
5. 다음 단계에서 필요한 지능 수준(intelligence_level: low, medium, high)을 추천해.

[투자 및 업무 원칙]
{principles_text}
- 모든 분석은 데이터의 무결성과 흐름을 최우선으로 한다.

[Capability Set (가용 도구)]
{tools_text}

[Active Workspace (현재 상태)]
{history_text}{profile_text}
"""

        # 4. 자율 선택을 유도하는 Few-Shot
        few_shot_example = """
[응답 예시]
{
  "persona": "퀀트 투자 전략가",
  "intent": "현대차 기술적 분석 및 매수 적정가 산출",
  "strategy": "주가 차트 분석 후 재무 건전성을 확인하여 최종 투자의견 제시",
  "required_tool": "trading_analyzer",
  "params": {"action": "analyze", "target": "현대차"},
  "intelligence_level": "high",
  "is_finished": false,
  "thought": "사용자가 현대차의 기술적 분석을 원하므로, 전문 분석 도구를 사용하여 차트와 지표를 먼저 확인한 후 재무 지표를 병합하겠습니다."
}
"""
        user = f"사용자 질문: {user_input}\n{few_shot_example}\n위 요청을 분석하여 최적의 전략과 도구를 JSON 형식으로 응답해줘."
        
        model_info = model_info or {}
        assigned_model = model_info.get("model")
        is_worker = (model_info.get("provider") == "worker")
        
        logger.info(f"🔍 [Autonomous Thinking] 전략 수립 중... (Model: {assigned_model})")
        result_text = await self.chat(system, user, use_remote=is_worker, model=assigned_model, step="Intent & Strategy Analysis")
        
        try:
            analysis = extract_json_from_text(result_text)

            if analysis:
                # 만약 LLM이 JSON 리스트를 반환했다면 첫 번째 요소를 취함
                if isinstance(analysis, list) and len(analysis) > 0:
                    analysis = analysis[0]
                
                if isinstance(analysis, dict):
                    # 도구 및 파라미터 추출
                    selected_tool = analysis.get("required_tool")
                    tool_params = analysis.get("params", {})
                    
                    # 1. required_tool이 리스트이거나 쉼표 포함 문자열인 경우 처리
                    if isinstance(selected_tool, str) and "," in selected_tool:
                        selected_tool = [t.strip() for t in selected_tool.split(",")]

                    if isinstance(selected_tool, list):
                        executed_tools = [h['tool'] for h in (research_history or [])]
                        new_tools = [t for t in selected_tool if t not in executed_tools]
                        selected_tool = new_tools[0] if new_tools else selected_tool[0]
                    
                    # 2. 파라미터 보정
                    if isinstance(tool_params, list):
                        if len(tool_params) > 0 and isinstance(tool_params[0], dict):
                            tool_params = tool_params[0]
                        else:
                            tool_params = {"query": str(tool_params)}
                            
                    # 3. dict 형태의 tool_val 처리
                    if isinstance(selected_tool, dict):
                        if "name" in selected_tool:
                            if "params" in selected_tool and isinstance(selected_tool["params"], dict):
                                tool_params.update(selected_tool["params"])
                            selected_tool = selected_tool["name"]
                        else:
                            selected_tool = next(iter(selected_tool.values())) if selected_tool else "web_researcher"
                    
                    logger.info(f"🎯 [Next Action]: {selected_tool}")
                    analysis["required_tool"] = selected_tool
                    analysis["params"] = tool_params
                    analysis["selected_model"] = assigned_model
                    return analysis
            
            logger.error(f"⚠️ [analyze_intent] 유효한 JSON 분석 결과를 찾을 수 없음: {result_text[:200]}")
        except Exception as e:
            logger.error(f"⚠️ [analyze_intent] 파싱 프로세스 에러: {e}")
        
        # 파싱 실패 시 무한 루프 방지: 조사 기록이 있다면 종료, 없으면 기본 검색
        is_finished = len(research_history or []) > 0
        return {
            "intent": user_input[:50], 
            "required_tool": "web_researcher" if not is_finished else None, 
            "params": {"query": user_input}, 
            "is_finished": is_finished,
            "thought": "파싱 오류로 인해 수집된 정보를 바탕으로 답변을 준비합니다." if is_finished else "파싱 오류로 기본 검색을 시도합니다."
        }


from core.cube_reasoner import CubeReasoner

# ==================== Orchestrator ====================
class Orchestrator:
    """메인 오케스트레이터 - LangGraph 기반 워크플로우 제어"""
    
    def __init__(self, local_mode: bool = True):
        self.config = Config()
        self.memory = MemoryManager()
        self.llm = OllamaClient(remote_url=self.config.WORKER_URL)
        self.reasoner = CubeReasoner(self.llm)
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
        
        result = await self.llm.analyze_intent(
            user_input, principles, user_profile, research_history, 
            model_info=state.get("current_model_info", {})
        )
        
        # [Autonomous Selection] LLM이 결정한 페르소나와 전략 저장
        state["persona"] = result.get("persona", state.get("persona"))
        state["strategy"] = result.get("strategy", state.get("strategy"))
        state["selected_tool"] = result.get("required_tool")
        state["tool_params"] = result.get("params", {})
        state["is_finished"] = result.get("is_finished", False)
        
        # [Dynamic Intelligence] LLM이 추천한 지능 수준에 맞춰 모델 재배정
        intel_level = result.get("intelligence_level")
        if intel_level and intel_level in ["low", "medium", "high", "deep"]:
            model_service = ModelAvailabilityService()
            # intelligence_level이 high/deep이면 Tier 3 모델 배정
            task_map = {"low": "low", "medium": "medium", "high": "deep", "deep": "deep"}
            new_model_info = await model_service.get_best_available_model(task=task_map.get(intel_level, "medium"))
            state["current_model_info"] = new_model_info
            state["selected_model"] = new_model_info["model"]
        else:
            state["selected_model"] = state.get("current_model_info", {}).get("model")
        
        return state
    
    async def execute_tool_node(self, state: AgentState) -> AgentState:
        """모든 도구를 서버 로컬에서 직접 실행"""
        tool_name = state.get("selected_tool")
        selected_model = state.get("selected_model") or state.get("current_model_info", {}).get("model")
        params = state.get("tool_params", {})
        # params가 리스트인 경우 방어적으로 딕셔너리로 변환
        if isinstance(params, list):
            logger.warning(f"⚠️ [execute_tool] params가 리스트로 들어옴. 딕셔너리로 변환 시도.")
            if len(params) > 0 and isinstance(params[0], dict):
                params = params[0]
            else:
                params = {"query": str(params)}
        elif not isinstance(params, dict):
            params = {}
            
        # 모델 정보를 도구에 전달하여 동적 처리 가능하도록 주입
        if "current_model_info" not in params:
            params["current_model_info"] = state.get("current_model_info", {})
        
        # 도구 이름이 리스트나 딕셔너리로 들어오는 경우 방어 로직
        if isinstance(tool_name, list) and len(tool_name) > 0:
            tool_name = tool_name[0]
        elif isinstance(tool_name, dict):
            logger.warning(f"⚠️ [execute_tool] tool_name이 객체로 들어옴: {tool_name}")
            if "name" in tool_name:
                # 객체 내부의 params가 더 구체적일 경우 병합
                if "params" in tool_name and isinstance(tool_name["params"], dict):
                    params.update(tool_name["params"])
                tool_name = tool_name["name"]
            else:
                # 예측 불가능한 객체인 경우 첫 번째 값 시도
                tool_name = next(iter(tool_name.values())) if tool_name else None
        
        if not tool_name or not isinstance(tool_name, str):
            logger.error(f"🚨 유효하지 않은 도구 이름: {tool_name} (Type: {type(tool_name)})")
            return state

        logger.info(f"🛠️ Executing tool locally: {tool_name}")
        try:
            # 동기 함수인 _execute_locally를 별도 스레드에서 실행하여 메인 루프와의 충돌 방지
            raw_result = await asyncio.to_thread(self._execute_locally, tool_name, params)
            
            # [사용자 요청] 정보 정리는 Tier 1(Cloud)이 담당
            svc = ModelAvailabilityService()
            summary_model_info = await svc.get_best_available_model(task="bulk") # Tier 1 우선
            summary_model = summary_model_info.get("model", selected_model)
            
            logger.info(f"📝 Summarizing with Tier{summary_model_info['tier']} ({summary_model})")
            summary = await self.llm.summarize_result(raw_result, model=summary_model)
            
            state["worker_result"] = raw_result
            state["worker_summary"] = summary
            
            if "research_history" not in state:
                state["research_history"] = []
            
            entry = {
                "tool": tool_name, "params": params, "result": raw_result, "summary": summary
            }
            LLMLogger.log_tool_usage(tool_name, params, summary)
            # 데이터 타입 검증
            if not isinstance(state["research_history"], list):
                logger.error(f"⚠️ research_history가 리스트가 아님: {type(state['research_history'])}")
                state["research_history"] = []
                
            state["research_history"].append(entry)
            
        except Exception as e:
            logger.error(f"🚨 Tool execution failed: {e}", exc_info=True)
            state["error"] = str(e)
            state["is_finished"] = True
            
        return state

    def _execute_locally(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """로컬 스킬/도구 실행 (2중 방어 적용)"""
        import importlib
        
        # 만약 도구 이름이 여전히 딕셔너리라면 강제 추출
        if isinstance(tool_name, dict):
            logger.warning(f"⚠️ [_execute_locally] tool_name이 객체임: {tool_name}")
            tool_name = tool_name.get("name") or next(iter(tool_name.values()))
            
        try:
            module_name = f"skills.{tool_name}"
            module = importlib.import_module(module_name)
            if hasattr(module, "run"):
                return module.run(params)
            return {"error": f"Module {module_name} has no 'run' function"}
        except Exception as e:
            logger.error(f"🚨 [_execute_locally] 도구 실행 중 오류: {e}")
            return {"error": str(e)}
    
    async def finalize_report_node(self, state: AgentState) -> AgentState:
        user_input = state.get("user_input", "")
        user_id = state.get("user_id", "default")
        worker_result = state.get("worker_result", {})
        principles = state.get("applied_principles", [])
        user_profile = self.memory.get_user_profile(user_id)
        
        # [중요] 다각도 추론(Synthesis)은 작업의 초기 복잡도와 상관없이 
        # 항상 가장 지능이 높은 'deep' 티어 모델(Tier 3 우선)을 사용합니다.
        # [Dynamic Intelligence] 리포트 생성도 전략에 따른 지능 수준 적용
        model_service = ModelAvailabilityService()
        deep_model_info = await model_service.get_best_available_model(task="deep")
        
        final_report = await self.reasoner.synthesis_node(
            worker_result=worker_result, 
            principles=principles, 
            user_input=user_input, 
            user_profile=user_profile, 
            model_info=deep_model_info,
            persona=state.get("persona"),
            strategy=state.get("strategy")
        )
        state["final_report"] = final_report
        return state
    
    async def _determine_task_complexity(self, user_input: str) -> str:
        """LLM을 사용하여 작업의 복잡도와 유형을 자율적으로 판단합니다 (Autonomous Routing)"""
        system = """너는 사용자 질문의 의도와 복잡도를 분석하여 처리 티어를 결정하는 지능형 라우터야.
        질문의 문맥을 파악하여 다음 중 하나로만 응답해:
        - bulk: 대량 데이터, 긴 문서 요약, 1만 토큰 이상의 컨텍스트 필요
        - realtime: 즉각적인 실시간 정보(시세 등), 단순 조회
        - deep: 고도의 논리적 추론, 복합 전략 설계, 심층 재무 분석
        - medium: 일반적인 질문, 도구 사용이 필요한 평이한 작업
        - low: 매우 단순한 인사, 확인, 단순 명령
        """
        user = f"질문: {user_input}\n\n유형(bulk, realtime, deep, medium, low) 중 하나만 단어로 응답해."
        
        try:
            # 라우팅은 성능과 비용이 검증된 Tier 1 (Groq/Gemini) 모델을 우선 사용
            router_model = "llama-3.1-8b-instant"
            result = await self.llm.chat(system, user, model=router_model, step="Task Routing")
            complexity = result.strip().lower()
            if any(c in complexity for c in ["bulk", "realtime", "deep", "medium", "low"]):
                for c in ["bulk", "realtime", "deep", "medium", "low"]:
                    if c in complexity: return c
        except Exception as e:
            logger.warning(f"⚠️ [Autonomous Routing] 실패, 규칙 기반으로 전환: {e}")
            
        return ModelAvailabilityService().calculate_task_complexity(user_input)

    async def run(self, user_input: str, user_id: str = "default", is_autonomous: bool = False) -> Dict[str, Any]:
        # 1. 가용 모델 동적 라우팅
        model_service = ModelAvailabilityService()
        
        # [Autonomous Selection] 키워드 방식이 아닌 LLM에게 질문하여 복잡도 판단
        complexity = await self._determine_task_complexity(user_input)
        best_model_info = await model_service.get_best_available_model(task=complexity)

        # LLM 클라이언트의 가용 상태를 서비스의 최신 상태와 동기화
        self.llm.worker_available = model_service.status.get("tier2_worker", False)

        initial_state = AgentState(
            user_input=user_input, user_id=user_id, research_history=[],
            iteration_count=0, applied_principles=[], is_finished=False,
            current_model_info=best_model_info, api_status=model_service.status
        )

        try:
            logger.info(f"🚀 [Model Routing] 선택 모델: {best_model_info['provider']} ({best_model_info['model']}) | task={complexity} | Worker: {'ONLINE' if self.llm.worker_available else 'OFFLINE'}")

            result = await self.graph.ainvoke(initial_state)
            return {
                "final_report": result.get("final_report"),
                "applied_principles": result.get("applied_principles"),
                "worker_result": result.get("worker_result"),
                "error": result.get("error")
            }
        except Exception as e:
            logger.error(f"🚨 [Orchestrator] Run failure: {str(e)}", exc_info=True)
            raise e

    def process_feedback(self, user_id: str, task_id: str, feedback_text: str) -> bool:
        # Simplified feedback for brevity, can be fully implemented if needed
        return True