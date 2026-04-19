"""
Manager Core - MacBook에서 실행되는 LangGraph 메인 로직
"""
from typing import Dict, Any, List, Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
import asyncio
import os


# 상태 정의
class NexusState(dict):
    """Nexus 상태"""
    task_id: str
    input_data: Dict[str, Any]
    worker_url: Optional[str]
    result: Optional[Dict[str, Any]]
    memory_context: List[Dict[str, Any]]
    error: Optional[str]


class ManagerCore:
    """메니저 코어"""
    
    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4", temperature=0.7)
        self.worker_url = os.getenv("WORKER_URL", "http://localhost:8000")
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """LangGraph 빌드"""
        graph = StateGraph(NexusState)
        
        # 노드 추가
        graph.add_node("analyze", self.analyze_task)
        graph.add_node("dispatch", self.dispatch_to_worker)
        graph.add_node("collect", self.collect_result)
        graph.add_node("reflect", self.reflect_with_memory)
        
        # 엣지 추가
        graph.set_entry_point("analyze")
        graph.add_edge("analyze", "dispatch")
        graph.add_edge("dispatch", "collect")
        graph.add_edge("collect", "reflect")
        graph.add_edge("reflect", END)
        
        return graph.compile()
    
    async def analyze_task(self, state: NexusState) -> NexusState:
        """작업 분석"""
        task_id = state.get("task_id")
        input_data = state.get("input_data", {})
        
        # 작업 유형 분석
        analysis = {
            "task_type": "market_analysis",
            "required_skill": "market_flow",
            "priority": "normal"
        }
        
        state["analysis"] = analysis
        return state
    
    async def dispatch_to_worker(self, state: NexusState) -> NexusState:
        """워커로 작업 디스패치"""
        import aiohttp
        
        analysis = state.get("analysis", {})
        task_id = state.get("task_id")
        
        async with aiohttp.ClientSession() as session:
            payload = {
                "task_id": task_id,
                "skill_name": analysis.get("required_skill"),
                "input_data": state.get("input_data", {})
            }
            try:
                async with session.post(f"{self.worker_url}/execute", json=payload) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        state["worker_result"] = result
                    else:
                        state["error"] = f"Worker error: {resp.status}"
            except Exception as e:
                state["error"] = str(e)
        
        return state
    
    async def collect_result(self, state: NexusState) -> NexusState:
        """결과 수집"""
        worker_result = state.get("worker_result", {})
        state["result"] = worker_result.get("result", {})
        return state
    
    async def reflect_with_memory(self, state: NexusState) -> NexusState:
        """메모리와 함께 반성"""
        # memory_manager를 통해 컨텍스트 저장
        state["memory_context"] = []
        return state
    
    async def run(self, task_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """작업 실행"""
        initial_state = NexusState(
            task_id=task_id,
            input_data=input_data,
            worker_url=self.worker_url,
            result=None,
            memory_context=[],
            error=None
        )
        
        result = await self.graph.ainvoke(initial_state)
        return result


if __name__ == "__main__":
    async def main():
        manager = ManagerCore()
        result = await manager.run("task_001", {"prices": [100, 105, 110]})
        print(result)
    
    asyncio.run(main())