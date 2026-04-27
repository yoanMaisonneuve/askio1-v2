"""
test_cold_start.py — Test Phase 4b : persistance cross-session
==============================================================
Dialogue délibérément différent qui DEVRAIT être enrichi par la
mémoire cross-session (règles sur l'architecture multi-couches,
la MEA, les cycles d'apprentissage robotique).
"""
import json, logging, sys
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
from askio1.cognitive_loop import CognitiveLoop

Path("data/logs").mkdir(parents=True, exist_ok=True)
LOG_FILE = f"data/logs/cold_start_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("askio1.cold_start_test")

# ─── Dialogue volontairement différent pour tester le transfert ───────────────
DIALOGUE = [
    # Doit bénéficier des règles sur l'architecture multi-couches mémorisées
    "Résume en 5 points ce que tu sais déjà sur les architectures cognitives multi-agents.",
    # Doit activer les patterns robotique stockés en MEA
    "À partir de ce que tu connais sur l'apprentissage par erreur, "
    "propose un protocole de test pour valider un système robotique.",
    # Doit utiliser les insights decay/importance de la session précédente
    "Comment déciderais-tu quelle règle mémoriser en priorité dans une MEA saturée ?",
]


def load_config(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run():
    config   = load_config()
    llm      = LLMClient(config)
    store    = MemoryStore(config)
    observer = Observer(llm, store)
    thinker  = Thinker(llm)
    executor = Executor(llm)
    reviewer = Reviewer(llm)
    mem_agent= MemoryAgent(llm, store)
    cloop    = CognitiveLoop(store, llm)

    session_id = f"cold_start_{datetime.now().strftime('%H%M%S')}"
    results = []

    logger.info("=" * 60)
    logger.info(f"TEST COLD START — {session_id}")
    logger.info("=" * 60)

    # ── Cold start : charge le résumé de la session précédente ────────────────
    cold_ctx = cloop.cold_start()
    if cold_ctx:
        logger.info("✅ COLD START RÉUSSI — contexte cross-session chargé :")
        logger.info(cold_ctx)
    else:
        logger.warning("⚠️  Aucun contexte cross-session trouvé")

    for turn, task in enumerate(DIALOGUE, 1):
        logger.info(f"\n{'─'*50}")
        logger.info(f"[Cycle {turn}] {task[:80]}")

        adaptive_ctx = cloop.cycle_start(turn, task)
        obs     = observer.observe(raw_text=task, context={"cycle": turn})
        snippets= store.retrieve_relevant(task)

        enriched = f"{adaptive_ctx}\n\n[MEA]\n{snippets}" if adaptive_ctx else snippets

        # Log explicite : est-ce que le contexte cross-session est injecté ?
        if turn == 1 and adaptive_ctx:
            logger.info("🔗 CONTEXTE CROSS-SESSION INJECTÉ DANS LE PENSEUR :")
            logger.info(adaptive_ctx[:400])
        logger.info(f"📚 SNIPPETS MEA ({len(snippets)} chars) :\n{snippets[:300]}")

        plan   = thinker.plan({"mission_id": session_id}, task, enriched)
        result = executor.execute(plan=plan, context={"cycle": turn})
        review = reviewer.review(result=result, goal=task, context={"cycle": turn})
        verdict= review.get("verdict", "?") if isinstance(review, dict) else "?"
        issues = review.get("issues", []) if isinstance(review, dict) else []

        mem_agent.build_entries(observer_output=obs, context={"cycle": turn})
        triggered = cloop.cycle_end(turn, verdict, issues, len(obs.get("candidates_for_memory", [])))

        logger.info(f"✓ Cycle {turn} — verdict={verdict} | consolidation={'OUI' if triggered else 'non'}")
        logger.info(f"Résultat (extrait) :\n{result[:600]}")

        results.append({
            "cycle":         turn,
            "task":          task,
            "cold_ctx_used": bool(adaptive_ctx and turn == 1),
            "mea_snippets":  snippets[:200],
            "verdict":       verdict,
            "result_extract":result[:500],
        })

    cloop.session_end(session_id, results)
    perf = cloop.stats.summary()

    logger.info(f"\n{'='*60}")
    logger.info(f"COLD START TEST TERMINÉ — {len(DIALOGUE)} cycles")
    logger.info(f"Performance : {perf['success_rate']:.0%} succès · failure_rate={perf['failure_rate']:.0%}")

    # ── Rapport JSON
    report_path = LOG_FILE.replace(".log", "_report.json")
    Path(report_path).write_text(
        json.dumps({
            "session_id": session_id,
            "cold_ctx_loaded": bool(cold_ctx),
            "cold_ctx_preview": cold_ctx[:300] if cold_ctx else "",
            "cycles": results,
            "perf": perf,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    logger.info(f"Rapport : {report_path}")
    return report_path

if __name__ == "__main__":
    run()
