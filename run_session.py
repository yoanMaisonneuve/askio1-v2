"""
run_session.py — Session de test Askio1 v2
==========================================
Lance une vraie conversation multi-cycles avec logging fichier.
Non-interactif : les tâches sont définies dans DIALOGUE ci-dessous.
"""
import json
import logging
import sys
import os
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from askio1.agents.observer import Observer
from askio1.agents.thinker import Thinker
from askio1.agents.executor import Executor
from askio1.agents.reviewer import Reviewer
from askio1.agents.memory_agent import MemoryAgent
from askio1.memory.store import MemoryStore
from askio1.tools.llm_client import LLMClient

# ─── Config logging ───────────────────────────────────────────────────────────
Path("data/logs").mkdir(parents=True, exist_ok=True)
LOG_FILE = f"data/logs/session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("askio1.session")

# ─── Dialogue scriptés (simulation de conversation) ─────────────────────────
DIALOGUE = [
    "Qui es-tu et qu'es-tu capable de faire comme système cognitif ?",
    "Propose-moi une architecture pour un agent qui apprend de ses erreurs en robotique.",
    "Quels sont les avantages d'une mémoire externe auto-construite par rapport à une base de données classique ?",
    "En te basant sur ce qu'on a dit jusqu'ici, quelles sont les 3 règles les plus importantes à respecter pour construire un système cognitif robuste ?",
    "Génère un fichier Python `mea_core.py` qui implémente un MemoryEntry avec scoring d'importance automatique et oubli progressif (decay).",
]


def load_config(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_session():
    config   = load_config()
    llm      = LLMClient(config)
    store    = MemoryStore(config)
    observer = Observer(llm, store)
    thinker  = Thinker(llm)
    executor = Executor(llm)
    reviewer = Reviewer(llm)
    mem_agent= MemoryAgent(llm, store)

    session_log = []
    mission_id  = f"session_{datetime.now().strftime('%H%M%S')}"

    logger.info("=" * 60)
    logger.info(f"ASKIO1 V2 — SESSION {mission_id}")
    logger.info("=" * 60)

    for turn, task in enumerate(DIALOGUE, 1):
        logger.info(f"\n{'─'*50}")
        logger.info(f"[Tour {turn}] TÂCHE : {task}")
        logger.info(f"{'─'*50}")

        # 1. Observer
        logger.info(f"[Tour {turn}] → Observer en cours...")
        obs = observer.observe(raw_text=task, context={"cycle": turn, "mission": mission_id})
        logger.info(f"[Observer] résumé : {obs.get('summary', '')[:200]}")
        candidates = obs.get("candidates_for_memory", [])
        logger.info(f"[Observer] {len(candidates)} candidat(s) mémoire détecté(s)")

        # 2. Penseur
        logger.info(f"[Tour {turn}] → Penseur en cours...")
        snippets = store.retrieve_relevant(task)
        plan = thinker.plan(mission_state={"mission_id": mission_id}, task=task, memory_snippets=snippets)
        steps = plan.get("steps", []) if isinstance(plan, dict) else []
        logger.info(f"[Penseur] {len(steps)} étape(s) planifiée(s)")
        for i, s in enumerate(steps[:3], 1):
            logger.info(f"  Étape {i}: {str(s)[:120]}")

        # 3. Exécuteur
        logger.info(f"[Tour {turn}] → Exécuteur en cours...")
        result = executor.execute(plan=plan, context={"cycle": turn})
        logger.info(f"[Exécuteur] réponse ({len(result)} chars) :\n{result[:600]}")

        # 4. Réviseur
        logger.info(f"[Tour {turn}] → Réviseur en cours...")
        review = reviewer.review(result=result, goal=task, context={"cycle": turn})
        verdict = review.get("verdict", "unknown") if isinstance(review, dict) else "unknown"
        issues  = review.get("issues", []) if isinstance(review, dict) else []
        logger.info(f"[Réviseur] verdict={verdict} · {len(issues)} problème(s)")

        # 5. Mémoire
        mem_agent.build_entries(observer_output=obs, context={"cycle": turn, "review": review})
        logger.info(f"[Mémoire] entrées sauvegardées")

        # Log structuré
        session_log.append({
            "tour": turn,
            "tache": task,
            "observer_summary": obs.get("summary", ""),
            "plan_steps": steps,
            "executor_result": result,
            "verdict": verdict,
            "issues": issues,
        })

        logger.info(f"[Tour {turn}] ✓ Complet — verdict={verdict}")

    # Réflexion finale MEA
    logger.info(f"\n{'='*50}")
    logger.info("[MEA] Réflexion finale — consolidation mémoire...")
    mem_agent.reflect(mission_id=mission_id)

    # Sauvegarde JSON de la session
    json_log = LOG_FILE.replace(".log", "_structured.json")
    with open(json_log, "w", encoding="utf-8") as f:
        json.dump(session_log, f, ensure_ascii=False, indent=2)

    entries = store.list_entries()
    logger.info(f"\n{'='*60}")
    logger.info(f"SESSION TERMINÉE — {len(DIALOGUE)} tours · {len(entries)} entrées LTM")
    logger.info(f"Log brut   : {LOG_FILE}")
    logger.info(f"Log JSON   : {json_log}")
    logger.info(f"{'='*60}")

    return LOG_FILE, json_log, session_log


if __name__ == "__main__":
    run_session()
