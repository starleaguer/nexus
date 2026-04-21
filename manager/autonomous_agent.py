import asyncio
import logging
from manager.manager_core import ManagerCore
from shared.config_loader import NexusConfig
from datetime import datetime
import json

logger = logging.getLogger(__name__)

class AutonomousAgent:
    def __init__(self, manager_core: ManagerCore):
        self.manager = manager_core
        self.is_running = False
        self._task = None
        
    def start(self):
        """백그라운드 루프 시작"""
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._loop())
            logger.info("자율 순환 루프(Autonomous Loop)가 시작되었습니다.")
            
    def stop(self):
        """백그라운드 루프 중지"""
        self.is_running = False
        if self._task:
            self._task.cancel()
            logger.info("자율 순환 루프가 중지되었습니다.")
            
    async def _loop(self):
        """주기적으로 시장을 모니터링하는 코어 루프"""
        while self.is_running:
            try:
                manifest = NexusConfig.load_manifest()
                # config에서 주기를 가져옴 (기본 3600초 = 1시간)
                interval = manifest.get("autonomous", {}).get("interval", 3600)
                
                logger.info(f"[Autonomous] 다음 정기 모니터링까지 대기합니다. ({interval}초 후 실행)")
                await asyncio.sleep(interval)

                sys_prompt = "정기 시장 자금 흐름 모니터링: 현재 주요 자산군(주식, 암호화폐, 채권 등)의 자금 흐름을 분석하고, 이전과 비교하여 구조적 변화나 특이사항이 있는지 심층 보고해."
                logger.info("[Autonomous] 정기 모니터링 시작...")
                
                # ManagerCore를 자율 모드로 실행
                result = await self.manager.run(sys_prompt, user_id="system", is_autonomous=True)
                
                if result and result.get("final_report"):
                    logger.info("[Autonomous] 정기 모니터링 리포트 생성 및 저장 완료.")
                
                if not self.is_running: break
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Autonomous] 루프 실행 중 오류: {e}")

