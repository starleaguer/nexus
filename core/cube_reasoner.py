import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class CubeReasoner:
    """
    다각도(구조와 흐름) 분석을 통해 최종 인사이트와 리포트를 도출하는 추론 엔진.
    """
    def __init__(self, llm_client):
        self.llm = llm_client

    async def synthesis_node(self, 
                             worker_result: Dict[str, Any], 
                             principles: List[Dict[str, Any]], 
                             user_input: str, 
                             user_profile: Optional[Dict[str, Any]] = None, 
                             model_info: Dict[str, Any] = None,
                             persona: Optional[str] = None,
                             strategy: Optional[str] = None) -> str:
        """
        [SynthesisNode]
        수집된 모든 정보를 통합하여 자율 페르소나 및 전략 기반의 최종 답변을 생성합니다.
        """
        principles_text = "\n".join([f"- {p.get('content', '')}" for p in principles])
        worker_text = json.dumps(worker_result, ensure_ascii=False, indent=2) if worker_result else "결과 없음"
        profile_text = f"\n\n[사용자 철학 및 성향]\n{user_profile['profile']}" if user_profile and user_profile.get("profile") else ""
        
        assigned_persona = persona or "지혜로운 서퍼(Wise Surfer)"
        strategy_text = f"\n[수립된 분석 전략]\n{strategy}" if strategy else ""

        system = f"""너는 {assigned_persona}야. {strategy_text}
사용자에게 제공할 최종 통찰을 위해 다음 프레임워크를 엄격히 적용해:

[제1원칙] 정보의 표면적인 내용보다는 그 기저에 깔린 '구조와 흐름'을 우선적으로 분석하라.
[큐브 관점] 현상을 단면적으로 보지 마라. 반드시 상반된(Opposing) 관점인 긍정(낙관) / 부정(비관) / 제3의 대안적(중립/반전) 시각을 모두 제시하여 현상을 입체적으로 조망하라.
[핵심 증류] 불필요한 노이즈와 불순물을 제거하고, 실전에서 즉시 사용할 수 있는 순도 높은 통찰(Insight)과 핵심 결론만을 추출하라.
{profile_text}"""
        
        user = f"[수집된 원본 정보]\n{worker_text}\n\n[적용할 분석 원칙]\n{principles_text}\n\n[사용자 원본 요청]\n{user_input}\n\n위 프레임워크와 정보를 바탕으로 큐브 관점이 적용된 최종 답변을 생성해."
        
        # 하드웨어 가속 및 모델 라우팅 로직
        use_remote = False
        target_model = None
        
        if model_info:
            target_model = model_info.get("model")
            provider = model_info.get("provider", "local")
            
            if provider == "worker":
                use_remote = True
                logger.info("⚡ [SynthesisNode] 고연산 감지: RTX-Worker 하드웨어 가속(GPU)을 활성화하여 심층 추론을 진행합니다.")
            elif provider == "local":
                logger.info("🏠 [SynthesisNode] Mac-Manager 로컬 자원을 사용하여 심층 추론을 진행합니다.")
            else:
                logger.info(f"🌐 [SynthesisNode] 상용 API ({provider} - {target_model})를 통해 추론을 진행합니다.")
        
        logger.info("🧠 [SynthesisNode] 수집 데이터 통합 및 다각도 큐브 추론 시작...")
        return await self.llm.chat(system, user, use_remote=use_remote, model=target_model, step="Cube Synthesis")
