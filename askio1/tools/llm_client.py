"""
llm_client.py — LLMClient multi-backend (Phase 7)
==================================================
Supporte 3 backends :
  - anthropic  : API Anthropic (Haiku, Sonnet, Opus)
  - ollama     : modèle local via Ollama HTTP (Qwen 2.5 7B etc.)
  - auto       : routing intelligent par tâche (défaut)

Routing "auto" :
  - PLAN / REFLECT / JUDGE  → Opus (claude-opus-4-6) si dispo, sinon Sonnet
  - OBSERVE / EXECUTE / REVIEW → Haiku (rapide, pas cher)
  - CONSOLIDATE / SEARCH    → Local Ollama si disponible, sinon Haiku

Heartbeat : vérifie la disponibilité d'Ollama toutes les 60s.
Si Ollama tombe → bascule automatiquement sur Anthropic pour les tâches locales.
"""

import logging
import os
import time
import threading
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

# ─── Modèles par tier ────────────────────────────────────────────────────────
TIER = {
    "opus":   "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
    "haiku":  "claude-haiku-4-5-20251001",
}

# Tâches → tier Anthropic
TASK_TIER = {
    "plan":        "opus",
    "reflect":     "opus",
    "judge":       "opus",
    "observe":     "haiku",
    "execute":     "haiku",
    "review":      "haiku",
    "consolidate": "haiku",   # local si dispo
    "search":      "haiku",   # local si dispo
    "default":     "haiku",
}

# Tâches déléguées au local si Ollama est up
LOCAL_TASKS = {"consolidate", "search", "default"}

OLLAMA_DEFAULT_HOST = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "qwen2.5:7b"
HEARTBEAT_INTERVAL = 60   # secondes


class OllamaBackend:
    """Backend Ollama — appel HTTP simple, pas de dépendance."""

    def __init__(self, host: str, model: str):
        self.host  = host.rstrip("/")
        self.model = model
        self._available: Optional[bool] = None
        self._last_check = 0.0

    def is_available(self) -> bool:
        now = time.time()
        if now - self._last_check < HEARTBEAT_INTERVAL:
            return bool(self._available)
        self._last_check = now
        try:
            import urllib.request
            url = f"{self.host}/api/tags"
            with urllib.request.urlopen(url, timeout=3) as r:
                self._available = r.status == 200
        except Exception:
            self._available = False
        status = "UP" if self._available else "DOWN"
        logger.debug(f"[Ollama] heartbeat → {status} ({self.model})")
        return bool(self._available)

    def call(self, system_prompt: str, user_prompt: str,
             temperature: float = 0.3, max_tokens: int = 4096) -> str:
        import json, urllib.request
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system",  "content": system_prompt},
                {"role": "user",    "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }).encode()
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
            return data["message"]["content"].strip()


class LLMClient:
    """
    Interface unifiée multi-backend.

    Modes :
      backend="auto"      — routing par tâche (recommandé)
      backend="anthropic" — toujours Anthropic
      backend="ollama"    — toujours local (erreur si absent)
    """

    def __init__(self, config: dict):
        cfg = config.get("llm", {})
        self.backend     = cfg.get("backend", "auto")
        self.max_tokens  = cfg.get("max_tokens", 4096)
        self.temperature = cfg.get("temperature", 0.3)

        # Backend Anthropic
        self._anthropic = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )
        self._default_model = os.getenv(
            "LLM_MODEL", cfg.get("model", TIER["haiku"])
        )

        # Backend Ollama
        ollama_host  = os.getenv("OLLAMA_HOST",  cfg.get("ollama_host",  OLLAMA_DEFAULT_HOST))
        ollama_model = os.getenv("OLLAMA_MODEL", cfg.get("ollama_model", OLLAMA_DEFAULT_MODEL))
        self._ollama = OllamaBackend(ollama_host, ollama_model)

        # Stats usage
        self._calls = {"anthropic": 0, "ollama": 0, "errors": 0}

        # Premier heartbeat en arrière-plan
        threading.Thread(target=self._ollama.is_available, daemon=True).start()

        logger.info(
            f"[LLMClient] backend={self.backend} "
            f"anthropic={self._default_model} "
            f"ollama={ollama_model}@{ollama_host}"
        )

    # ─── API publique ────────────────────────────────────────────────────────

    def call(self, system_prompt: str, user_prompt: str,
             task: str = "default") -> str:
        """
        Appel LLM avec routing automatique selon la tâche.
        task: 'plan' | 'observe' | 'execute' | 'review' | 'reflect' |
              'consolidate' | 'judge' | 'search' | 'default'
        """
        if self.backend == "ollama":
            return self._call_ollama(system_prompt, user_prompt)

        if self.backend == "anthropic":
            model = TIER.get(TASK_TIER.get(task, "default"), self._default_model)
            return self._call_anthropic(system_prompt, user_prompt, model)

        # Auto routing
        return self._auto_route(system_prompt, user_prompt, task)

    def usage_stats(self) -> dict:
        return dict(self._calls)

    # ─── Routing auto ────────────────────────────────────────────────────────

    def _auto_route(self, system: str, user: str, task: str) -> str:
        tier = TASK_TIER.get(task, "default")

        # Tâches locales → Ollama si disponible
        if task in LOCAL_TASKS and self._ollama.is_available():
            try:
                result = self._call_ollama(system, user)
                logger.debug(f"[LLMClient] routed {task} → ollama")
                return result
            except Exception as e:
                logger.warning(f"[LLMClient] ollama failed ({e}), fallback anthropic")

        # Anthropic avec tier adapté
        model = TIER.get(tier, self._default_model)
        logger.debug(f"[LLMClient] routed {task} → anthropic/{model}")
        return self._call_anthropic(system, user, model)

    # ─── Backends ────────────────────────────────────────────────────────────

    def _call_anthropic(self, system: str, user: str, model: str) -> str:
        try:
            resp = self._anthropic.messages.create(
                model=model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            self._calls["anthropic"] += 1
            return resp.content[0].text.strip()
        except Exception as e:
            self._calls["errors"] += 1
            logger.error(f"[LLMClient] anthropic error: {e}")
            raise

    def _call_ollama(self, system: str, user: str) -> str:
        try:
            result = self._ollama.call(system, user, self.temperature, self.max_tokens)
            self._calls["ollama"] += 1
            return result
        except Exception as e:
            self._calls["errors"] += 1
            logger.error(f"[LLMClient] ollama error: {e}")
            raise
