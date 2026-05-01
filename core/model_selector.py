"""
ModelAvailabilityService - 3-Tier 하드웨어 인식 LLM 라우팅 엔진
=================================================================

[시스템 티어 정의]
  Tier 1 │ Cloud Lookout   │ Gemini API, Groq API
         │                 │ 강점: 초대형 컨텍스트 창, 무료/저비용
         │                 │ 용도: 대규모 스캔, 요약, 웹 분석, 멀티미디어

  Tier 2 │ Fast Sprinter   │ RTX Worker (In-house GPU, 원격 Ollama)
         │                 │ 강점: 압도적 Token/sec, 무제한 로컬
         │                 │ 용도: 실시간 에이전트 루프, 반복 코드 생성

  Tier 3 │ Deep Philosopher│ M1 Max 64GB Manager (로컬 Ollama)
         │                 │ 강점: 64GB 통합 메모리 → 70B+ 모델 구동
         │                 │ 용도: 복잡한 전략 설계, 고난도 추론, 논리 검증

[라우팅 우선순위]
  "bulk"    → Tier1 (대량 데이터 / 멀티미디어 / 10K+ 토큰)
  "realtime"→ Tier2 (5초 이내, 에이전트 루프, 실시간 처리)
  "deep"    → Tier3 (고난도 추론, 30B+ 지능)
  "fast"    → Tier1 > Tier2 (속도+정확도 균형)
  "high"    → Tier3 > Tier1 (정확도 우선)
  "medium"  → Tier2 > Tier1 > Tier3
  "low"     → Tier2 > Tier3 > Tier1
"""

import os
import re
import aiohttp
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from core.config_loader import NexusConfig

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 모델 성능 데이터베이스 (하드웨어 독립적 사양 정의)
# 새 모델 추가 시 이 딕셔너리에만 항목을 추가하면 됩니다.
# ─────────────────────────────────────────────────────────────────────────────
CLOUD_MODEL_DB: Dict[str, Dict] = {
    # Gemini API
    "models/gemini-flash-lite-latest": {
        "tier": 1, "provider": "gemini",
        "iq": 85, "speed": 18, "context_k": 1000,
        "cost_per_1k": 0.0,
        "url": "api",
    },
    "models/gemini-flash-latest": {
        "tier": 1, "provider": "gemini",
        "iq": 92, "speed": 13, "context_k": 1000,
        "cost_per_1k": 0.0,
        "url": "api",
    },
    "models/gemini-pro-latest": {
        "tier": 1, "provider": "gemini",
        "iq": 94, "speed": 4, "context_k": 2000,
        "cost_per_1k": 0.0,
        "url": "api",
    },
    # Groq API
    "llama-3.3-70b-versatile": {
        "tier": 3, "provider": "groq",
        "iq": 91, "speed": 15, "context_k": 128,
        "cost_per_1k": 0.59,
        "url": "api",
    },
    "llama-3.1-8b-instant": {
        "tier": 1, "provider": "groq",
        "iq": 74, "speed": 20, "context_k": 128,
        "cost_per_1k": 0.05,
        "url": "api",
    },
}

# RTX Worker / M1 Local 모델 사이즈별 기본 성능 추정치
LOCAL_SIZE_METRICS: Dict[str, Dict] = {
    "70b":  {"iq": 90, "speed": 3},
    "32b":  {"iq": 85, "speed": 5},
    "27b":  {"iq": 83, "speed": 5},
    "14b":  {"iq": 78, "speed": 7},
    "12b":  {"iq": 77, "speed": 8},
    "9b":   {"iq": 75, "speed": 9},
    "8b":   {"iq": 73, "speed": 9},
    "7b":   {"iq": 71, "speed": 10},
    "4b":   {"iq": 66, "speed": 12},
    "3b":   {"iq": 63, "speed": 14},
}

# RTX 4070 Ti Super: 16GB VRAM, 빠른 추론
TIER2_HW = {
    "hw_bonus_base": 30,       # 기본 속도 보너스
    "vram_limit_b": 14,        # VRAM 초과 기준 (파라미터 B 단위)
    "vram_overflow_penalty": 20,
    "latency_divisor": 35,
}

# M1 Max 64GB: 통합 메모리, 대형 모델 안정 구동
TIER3_HW = {
    "hw_bonus_base": 10,
    "large_model_bonus": 12,   # 27B+ 모델 보너스
    "large_model_threshold_b": 20,
    "latency_divisor": 50,
}


class ModelAvailabilityService:
    """
    3-Tier 하드웨어 인식 LLM 라우팅 엔진.
    작업 유형과 각 티어의 실시간 가용성을 기반으로 최적 모델을 선택합니다.
    """

    # ─────────────────────────────────────────────────────────────────────────────
    # 공유 상태 (부하 분산 및 캐싱용)
    # ─────────────────────────────────────────────────────────────────────────────
    _cycle_counter = 0
    _status_cache: Dict[str, Any] = {}
    _last_update = 0.0
    _CACHE_TTL = 30.0  # 30초간 상태 캐싱

    def __init__(self):
        # 각 티어/프로바이더 가용성 상태
        self.status: Dict[str, bool] = {
            "tier1_gemini": False,
            "tier1_groq":   False,
            "tier2_worker": False,
            "tier3_local":  False,
        }
        # Ollama 서버 응답 지연(ms)
        self.latency_ms: Dict[str, float] = {
            "tier2_worker": 9999.0,
            "tier3_local":  9999.0,
        }

    # ─── 헬퍼: Ollama 핑 ─────────────────────────────────────────────────────

    async def _ping_ollama(self, url: str, timeout: float = 2.5) -> float:
        """Ollama 서버 핑. 응답 속도(ms) 반환, 실패 시 9999.0."""
        t0 = time.time()
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                async with session.get(f"{url}/api/tags") as resp:
                    if resp.status == 200:
                        return (time.time() - t0) * 1000
                    logger.debug(f"[Ping] {url} status={resp.status}")
        except asyncio.TimeoutError:
            logger.debug(f"[Ping] {url} timeout")
        except Exception as e:
            logger.debug(f"[Ping] {url} error: {e}")
        return 9999.0

    async def _ping_mlx(self, url: str, timeout: float = 2.5) -> float:
        """MLX-LM 서버 핑 (OpenAI 호환 /v1/models). 응답 속도(ms) 반환, 실패 시 9999.0."""
        t0 = time.time()
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                async with session.get(f"{url}/v1/models") as resp:
                    if resp.status == 200:
                        return (time.time() - t0) * 1000
                    logger.debug(f"[MLX Ping] {url} status={resp.status}")
        except asyncio.TimeoutError:
            logger.debug(f"[MLX Ping] {url} timeout")
        except Exception as e:
            logger.debug(f"[MLX Ping] {url} error: {e}")
        return 9999.0

    # ─── 상태 업데이트 ────────────────────────────────────────────────────────

    async def update_status(self, force: bool = False):
        """모든 티어의 실시간 가용성을 병렬로 체크합니다. (30초 캐싱 적용)"""
        now = time.time()
        if not force and (now - ModelAvailabilityService._last_update < self._CACHE_TTL) and ModelAvailabilityService._status_cache:
            self.status = ModelAvailabilityService._status_cache["status"].copy()
            self.latency_ms = ModelAvailabilityService._status_cache["latency"].copy()
            return

        manifest = NexusConfig.load_manifest()
        worker_url = NexusConfig.get_worker_url()
        mlx_url    = manifest.get("local", {}).get("url", "http://localhost:8080")

        # Tier 2 (Ollama Worker) / Tier 3 (MLX 서버) 핑을 병렬 실행
        t2_lat, t3_lat = await asyncio.gather(
            self._ping_ollama(worker_url),
            self._ping_mlx(mlx_url),
        )

        self.latency_ms["tier2_worker"] = t2_lat
        self.latency_ms["tier3_local"]  = t3_lat

        self.status["tier2_worker"] = t2_lat < 3000
        self.status["tier3_local"]  = t3_lat < 3000
        self.status["tier1_gemini"] = bool(os.getenv("GEMINI_API_KEY"))
        self.status["tier1_groq"]   = bool(os.getenv("GROQ_API_KEY"))

        # 캐시 업데이트
        ModelAvailabilityService._status_cache = {
            "status": self.status.copy(),
            "latency": self.latency_ms.copy()
        }
        ModelAvailabilityService._last_update = now

        logger.info(
            f"🛰️  [Tier Status] "
            f"Tier1-Gemini:{self.status['tier1_gemini']} | "
            f"Tier1-Groq:{self.status['tier1_groq']} | "
            f"Tier2-Worker:{self.status['tier2_worker']}({t2_lat:.0f}ms) | "
            f"Tier3-MLX:{self.status['tier3_local']}({t3_lat:.0f}ms)"
        )

    # ─── 로컬 모델 메트릭 추정 ───────────────────────────────────────────────

    def _local_metrics(self, model_name: str) -> Dict[str, int]:
        """모델명에서 파라미터 크기를 추출해 IQ/Speed를 추정합니다.
        명시적 이름 매핑이 있으면 우선 사용하고, 없으면 사이즈 키워드로 추정합니다."""
        name_lower = model_name.lower()

        # ── 명시적 모델명 매핑 (태그/별칭 포함) ──────────────────────────────
        # qwen3.5 = Qwen3 7.6B dense (RTX 16GB에 최적)
        if "qwen3.5" in name_lower or "qwen3-7" in name_lower:
            return {"iq": 76, "speed": 12}   # 7.6B dense, RTX에서 매우 빠름
        if "qwen3" in name_lower and "30b" in name_lower:
            return {"iq": 85, "speed": 6}
        if "gemma4" in name_lower and "e4b" in name_lower:
            return {"iq": 68, "speed": 14}   # Gemma4 4B: 경량 빠름
        if "llama3.2" in name_lower and ("1b" in name_lower or "3b" in name_lower):
            return {"iq": 62, "speed": 16}

        # ── 사이즈 키워드 일반 매칭 ──────────────────────────────────────────
        for size_key, metrics in LOCAL_SIZE_METRICS.items():
            if size_key in name_lower:
                return metrics
        return {"iq": 72, "speed": 10}  # 기본값 (소형~중형 추정)

    def _extract_param_b(self, model_name: str) -> float:
        """모델명에서 파라미터 수(B)를 숫자로 추출합니다."""
        match = re.search(r"(\d+(?:\.\d+)?)b", model_name.lower())
        return float(match.group(1)) if match else 7.0

    # ─── 복잡도 분석 ─────────────────────────────────────────────────────────

    def calculate_task_complexity(self, content: str) -> str:
        """
        텍스트 내용의 전문성·길이를 분석하여 작업 복잡도를 산출합니다.
        반환값: "bulk" | "deep" | "high" | "medium" | "low"
        """
        if not content:
            return "low"

        # 10,000 토큰 기준 (≈ 40,000자) → bulk
        if len(content) > 40_000:
            return "bulk"

        content_lower = content.lower()
        indicators = {
            "financial": len(re.findall(
                r"\b(?:ebitda|dcf|roic?|wacc|beta|volatility|sharpe|재무제표|현금흐름|영업이익)\b",
                content_lower)),
            "numerical": len(re.findall(r"\$?[\d,]+\.?\d*[%kmbKMB]?", content)),
            "comparative": len(re.findall(
                r"\b(?:versus|compared|relative|outperform|underperform|대비|비교|상회|하회)\b",
                content_lower)),
            "temporal": len(re.findall(
                r"\b(?:quarterly|q[1-4]|fy|yoy|qoq|annual|분기|연간|전년동기)\b",
                content_lower)),
            "technical": len(re.findall(
                r"\b(?:support|resistance|breakout|rsi|macd|sma|ema|지지선|저항선|돌파|아키텍처|알고리즘)\b",
                content_lower)),
        }

        total = sum(indicators.values())
        word_count = max(len(content.split()), 1)
        score = min(total / max(word_count / 50, 1), 1.0)
        if len(content) > 2000:
            score = min(score + 0.15, 1.0)

        if score > 0.65:
            return "deep"
        elif score > 0.35:
            return "high"
        elif score > 0.15:
            return "medium"
        else:
            return "low"

    # ─── 모델 DB 구성 ────────────────────────────────────────────────────────

    def _build_model_db(self) -> Dict[str, Dict]:
        """매니페스트 설정 + 클라우드 모델 DB를 합쳐 전체 후보군을 반환합니다.
        local/worker 모델이 같은 이름이라도 키 충돌 없이 별도 항목으로 유지합니다."""
        manifest = NexusConfig.load_manifest()
        worker_model = manifest.get("models", {}).get("worker", "gemma2:9b")
        worker_url   = NexusConfig.get_worker_url()

        # Tier 3: MLX 서버에서 명시적으로 읽어옴
        local_cfg    = manifest.get("local", {})
        local_model  = local_cfg.get("model", manifest.get("models", {}).get("manager", "Qwen3.6-27B-4bit"))
        local_url    = local_cfg.get("url", "http://localhost:8080")

        wm = self._local_metrics(worker_model)
        lm = self._local_metrics(local_model)
        wp = self._extract_param_b(worker_model)
        lp = self._extract_param_b(local_model)

        db: Dict[str, Dict] = {}

        # Tier 3 – Deep Philosopher (M1 Max + MLX, OpenAI 호환)
        db[f"local::{local_model}"] = {
            "tier": 3, "provider": "local",
            "model_name": local_model,
            "iq": lm["iq"], "speed": lm["speed"],
            "context_k": 131,  # Qwen3 27B: 128K 컨텍스트
            "param_b": lp,
            "url": local_url,
        }

        # Tier 2 – Fast Sprinter (RTX Worker, 원격 Ollama)
        db[f"worker::{worker_model}"] = {
            "tier": 2, "provider": "worker",
            "model_name": worker_model,
            "iq": wm["iq"], "speed": wm["speed"],
            "context_k": 128, "param_b": wp,
            "url": worker_url,
        }

        # Tier 1 – Cloud Lookout (API)
        for k, v in CLOUD_MODEL_DB.items():
            entry = dict(v)
            entry["model_name"] = k
            db[k] = entry

        return db

    # ─── 후보군 수집 ─────────────────────────────────────────────────────────

    def _get_tier_candidates(
        self, model_db: Dict[str, Dict], tier: int
    ) -> List[str]:
        """특정 티어 중 현재 가용 상태인 모델 목록을 반환합니다."""
        result = []
        for name, m in model_db.items():
            if m["tier"] != tier:
                continue
            p = m["provider"]
            if p == "gemini" and self.status["tier1_gemini"]:
                result.append(name)
            elif p == "groq" and self.status["tier1_groq"]:
                result.append(name)
            elif p == "worker" and self.status["tier2_worker"]:
                result.append(name)
            elif p == "local" and self.status["tier3_local"]:
                result.append(name)
        return result

    # ─── 개별 모델 점수 계산 ─────────────────────────────────────────────────

    def _score(self, name: str, m: Dict, task: str) -> float:
        """작업 유형별 가중치로 모델 점수를 계산합니다."""
        iq    = m["iq"]
        speed = m["speed"]
        # API 모델 비용 패널티 (무료 모델은 0)
        cost_p = m.get("cost_per_1k", 0.0) * 5

        # 하드웨어 보너스
        hw = 0.0
        lat_pen = 0.0

        if m["provider"] == "worker":
            hw = float(TIER2_HW["hw_bonus_base"])
            if m.get("param_b", 7) > TIER2_HW["vram_limit_b"]:
                hw -= TIER2_HW["vram_overflow_penalty"]
            lat_pen = self.latency_ms["tier2_worker"] / TIER2_HW["latency_divisor"]

        elif m["provider"] == "local":
            hw = float(TIER3_HW["hw_bonus_base"])
            if m.get("param_b", 7) >= TIER3_HW["large_model_threshold_b"]:
                hw += TIER3_HW["large_model_bonus"]
            lat_pen = self.latency_ms["tier3_local"] / TIER3_HW["latency_divisor"]

        # 작업 유형별 스코어링 공식
        if task in ("bulk", "fast"):
            # 속도 + 정확도 균형, 대형 컨텍스트 보너스
            ctx_bonus = min(m.get("context_k", 32) / 50, 15.0)
            s = (iq * 2.0) + (speed * 3.0) + ctx_bonus - cost_p + hw - lat_pen

        elif task == "realtime":
            # 속도 압도적 우선
            s = (speed * 5.0) + (iq * 0.5) - cost_p + hw - lat_pen

        elif task in ("deep", "high"):
            # 지능(IQ) 압도적 우선
            s = (iq * 5.0) + (speed * 0.3) - cost_p + hw - lat_pen

        elif task == "medium":
            s = (iq * 2.5) + (speed * 1.5) - cost_p + hw - lat_pen

        else:  # "low"
            s = (speed * 3.0) + (iq * 1.0) - cost_p + hw - lat_pen

        return s

    # ─── 최적 모델 선택 ──────────────────────────────────────────────────────

    def _best_in_tier(
        self, tier: int, task: str, model_db: Dict[str, Dict]
    ) -> Optional[Dict[str, str]]:
        """지정 티어 내에서 점수가 가장 높은 모델을 반환합니다. 없으면 None."""
        candidates = self._get_tier_candidates(model_db, tier)
        if not candidates:
            return None

        best_name, best_score = None, -1e9
        for name in candidates:
            m = model_db[name]
            sc = self._score(name, m, task)
            if sc > best_score:
                best_score, best_name = sc, name

        if best_name:
            m = model_db[best_name]
            # model_name 필드가 있으면 실제 Ollama 모델명을 반환 (local::xxx, worker::xxx 접두사 제거)
            real_model_name = m.get("model_name", best_name)
            logger.info(
                f"  ✓ Tier{tier} 후보: {real_model_name} ({m['provider']}) "
                f"score={best_score:.1f}"
            )
            return {
                "tier":     tier,
                "provider": m["provider"],
                "model":    real_model_name,
                "url":      m["url"],
            }
        return None

    async def get_best_available_model(
        self, task: str = "medium", tier: int = None
    ) -> Dict[str, str]:
        """
        [3-Tier 라우팅 엔진]
        작업 유형에 따라 최적 티어를 선택하고, 해당 티어가 불가용이면
        대체 티어로 자동 Fallback합니다.
        
        tier가 지정된 경우, 해당 티어를 최우선으로 선택하며 부하 분산(Load Balancing)을 건너뜁니다.

        task 유형:
          "bulk"     → Tier1 (대량 데이터, 10K+ 토큰, 멀티미디어)
          "realtime" → Tier2 (5초 이내, 에이전트 루프, 실시간 주식)
          "deep"     → Tier3 (고난도 추론, 30B+ 지능 필요)
          "fast"     → Tier1 > Tier2 (속도+정확도 균형)
          "high"     → Tier3 > Tier1 (정확도 우선)
          "medium"   → Tier2 > Tier1 > Tier3
          "low"      → Tier2 > Tier3 > Tier1
        """
        await self.update_status()
        model_db = self._build_model_db()

        # ── 특정 티어 고정 모드 ──────────────────────────────────────────────
        if tier:
            result = self._best_in_tier(tier, task, model_db)
            if result:
                logger.info(f"📍 [Fixed Tier] {result['model']} (Tier{tier}) selected as requested.")
                return result
            logger.warning(f"⚠️ 요청된 Tier{tier}가 가용하지 않아 일반 라우팅으로 전환합니다.")

        # ── 작업별 티어 우선순위 정의 ────────────────────────────────────────
        # 순서대로 시도 → 앞 티어가 불가용이면 다음으로 Fallback
        PRIORITY: Dict[str, List[int]] = {
            "bulk":     [1, 3, 2],   # Cloud 우선 (대형 컨텍스트) → Deep → Sprinter
            "realtime": [2, 1, 3],   # RTX Sprinter 우선 → Cloud → Deep
            "deep":     [3, 2, 1],   # ★ M1 Max 우선 → RTX → Cloud (고난도 추론)
            "fast":     [1, 2, 3],   # Cloud 우선 (속도+정확) → Sprinter → Deep
            "high":     [3, 1, 2],   # ★ M1 Max 우선 → Cloud → Sprinter (정확도 우선)
            "medium":   [2, 1, 3],   # RTX Sprinter 우선 → Cloud → Deep
            "low":      [2, 3, 1],   # RTX Sprinter 우선 → Deep → Cloud
        }
        priority = PRIORITY.get(task, PRIORITY["medium"])

        logger.info(f"🎯 [Routing] task='{task}' | 티어 우선순위: Tier{priority}")

        # ── 부하 분산 로직 (Load Balancing) ──────────────────────────────────
        # 여러 작업이 있을 때 Tier 1(Cloud)과 Tier 2(Worker)를 골고루 사용하도록 분산합니다.
        # 대상: 일반적인 작업 유형 (medium, fast, realtime, low)
        if task in ("medium", "fast", "realtime", "low"):
            # 가용한 모든 티어 후보군 수집
            available_results = {}
            for t in priority:
                if t in (1, 2):  # Tier 1, 2만 분산 대상
                    res = self._best_in_tier(t, task, model_db)
                    if res:
                        available_results[t] = res

            # Tier 1과 Tier 2가 모두 가용할 경우 교차 선택
            if 1 in available_results and 2 in available_results:
                ModelAvailabilityService._cycle_counter += 1
                selected_tier = 1 if ModelAvailabilityService._cycle_counter % 2 == 0 else 2
                
                result = available_results[selected_tier]
                logger.info(
                    f"⚖️ [Load Balance] Tier1 & Tier2 교차 분산 선택 -> "
                    f"Tier{selected_tier} ({result['model']})"
                )
                return result

        # ── 일반 우선순위 로직 ────────────────────────────────────────────────
        for tier in priority:
            result = self._best_in_tier(tier, task, model_db)
            if result:
                logger.info(
                    f"🏆 [Final] {result['model']} (Tier{result['tier']}, "
                    f"{result['provider']}) selected for task='{task}'"
                )
                return result

        # 모든 티어 실패
        logger.error("🚨 [Fatal] 가용 모델 없음 — 로컬 Fallback 시도")
        manifest = NexusConfig.load_manifest()
        local_model = manifest.get("models", {}).get("manager", "gemma2:27b")
        return {
            "tier": 3, "provider": "local",
            "model": local_model,
            "url": "http://127.0.0.1:11434",
        }
