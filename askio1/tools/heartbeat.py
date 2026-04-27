"""
heartbeat.py — Heartbeat & Router local/cloud (Phase 7)
========================================================
Surveille en continu la disponibilité d'Ollama.
Expose un rapport de santé lisible par le dashboard et run_continuous.

Le LLMClient consulte OllamaBackend.is_available() qui a son propre cache.
Ce module ajoute :
  - Un thread de monitoring périodique avec historique
  - Un rapport JSON /data/heartbeat.json lisible par l'API
  - Des alertes log si Ollama tombe ou revient
"""

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HEARTBEAT_FILE = Path("data/heartbeat.json")
CHECK_INTERVAL = 30   # secondes


class HeartbeatMonitor:
    """
    Thread daemon qui vérifie Ollama toutes les CHECK_INTERVAL secondes
    et écrit un rapport JSON.
    """

    def __init__(self, ollama_host: str = "http://localhost:11434",
                 ollama_model: str = "qwen2.5:7b"):
        self.ollama_host  = ollama_host
        self.ollama_model = ollama_model
        self._running     = False
        self._thread: Optional[threading.Thread] = None
        self.status = {
            "ollama_up":     False,
            "last_check":    None,
            "uptime_pct":    0.0,
            "checks_total":  0,
            "checks_up":     0,
            "model":         ollama_model,
            "host":          ollama_host,
        }
        HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="heartbeat")
        self._thread.start()
        logger.info(f"[Heartbeat] démarré — vérifie {self.ollama_host} toutes les {CHECK_INTERVAL}s")

    def stop(self):
        self._running = False
        logger.info("[Heartbeat] arrêté")

    def _loop(self):
        while self._running:
            self._check()
            time.sleep(CHECK_INTERVAL)

    def _check(self):
        try:
            import urllib.request
            with urllib.request.urlopen(f"{self.ollama_host}/api/tags", timeout=3) as r:
                up = r.status == 200
        except Exception:
            up = False

        was_up = self.status["ollama_up"]
        self.status["ollama_up"]   = up
        self.status["last_check"]  = datetime.utcnow().isoformat()
        self.status["checks_total"] += 1
        if up:
            self.status["checks_up"] += 1
        self.status["uptime_pct"] = round(
            100 * self.status["checks_up"] / max(self.status["checks_total"], 1), 1
        )

        # Alertes sur changement d'état
        if up and not was_up and self.status["checks_total"] > 1:
            logger.info(f"[Heartbeat] ✅ Ollama est REVENU ({self.ollama_model})")
        elif not up and was_up:
            logger.warning(f"[Heartbeat] ⚠️  Ollama est TOMBÉ — bascule sur Anthropic")

        # Écrit le rapport
        try:
            HEARTBEAT_FILE.write_text(
                json.dumps(self.status, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

        level = logging.DEBUG if self.status["checks_total"] % 10 else logging.INFO
        logger.log(level, f"[Heartbeat] ollama={'UP' if up else 'DOWN'} uptime={self.status['uptime_pct']}%")

    def report(self) -> dict:
        return dict(self.status)
