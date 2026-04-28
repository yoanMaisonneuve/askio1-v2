"""
run_continuous.py — Mode Daemon Askio1 v2 (Phase 7)
====================================================
Le système tourne en continu, apprend, et travaille sur un projet.

Boucle principale :
  1. Charge la prochaine tâche depuis TASKS_FILE (JSON list)
  2. Si la liste est vide → entre en mode "exploration autonome"
     (génère lui-même des sous-tâches à partir de son objectif)
  3. Exécute le cycle cognitif complet (Observer→Penseur→Exec→Review→Mémoire)
  4. Si la tâche implique une recherche web → WebSearchAgent activé
  5. Toutes les K cycles → consolidation MEA + rapport de progression
  6. Ctrl+C → sauvegarde propre + résumé cross-session

Usage :
  python run_continuous.py                      # tâches depuis tasks.json
  python run_continuous.py --goal "Concevoir le châssis d'un robot 3D imprimable"
  python run_continuous.py --interval 10        # pause entre cycles (sec)

Fichiers :
  tasks.json         — file de tâches (modifiable pendant que ça tourne)
  data/progress.json — état de progression sauvegardé
"""

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from askio1.agents.executor import Executor
from askio1.agents.memory_agent import MemoryAgent
from askio1.agents.observer import Observer
from askio1.agents.reviewer import Reviewer
from askio1.agents.thinker import Thinker
from askio1.agents.web_search import WebSearchAgent
from askio1.cognitive_loop import CognitiveLoop
from askio1.memory.store import MemoryStore
from askio1.tools.heartbeat import HeartbeatMonitor
from askio1.tools.llm_client import LLMClient

# ─── Fichiers ─────────────────────────────────────────────────────────────────
TASKS_FILE      = Path("tasks.json")
COMPLETED_FILE  = Path("data/completed_tasks.json")
PROGRESS_FILE   = Path("data/progress.json")
STATUS_FILE     = Path("data/status.json")

# ─── Logging ──────────────────────────────────────────────────────────────────
Path("data/logs").mkdir(parents=True, exist_ok=True)
LOG_FILE = f"data/logs/continuous_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("askio1.continuous")

# ─── Prompt d'exploration autonome ────────────────────────────────────────────
SELF_TASK_SYSTEM = """Tu es le planificateur d'un système cognitif autonome.
Ton objectif global est : {goal}

Tu as accès à ta mémoire MEA :
{memory}

Génère la prochaine tâche concrète et actionnable à accomplir pour progresser vers l'objectif.
La tâche doit être spécifique, réalisable en 1 cycle, et s'appuyer sur ce que tu sais déjà.

Réponds en JSON : {{"task": "...", "rationale": "...", "needs_web": true|false}}"""


def load_config():
    return yaml.safe_load(open("config.yaml", encoding="utf-8"))


def load_tasks() -> list:
    if not TASKS_FILE.exists():
        return []
    try:
        return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def pop_task() -> str | None:
    tasks = load_tasks()
    if not tasks:
        return None
    task = tasks.pop(0)
    TASKS_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    return task


def log_completed_task(task: str, verdict: str, cycle: int):
    """Ajoute la tâche complétée dans completed_tasks.json."""
    COMPLETED_FILE.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if COMPLETED_FILE.exists():
        try:
            history = json.loads(COMPLETED_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    history.append({
        "cycle": cycle,
        "task": task,
        "verdict": verdict,
        "completed_at": datetime.utcnow().isoformat(),
    })
    COMPLETED_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def write_status(session_id: str, cycle: int, task: str, verdict: str,
                 queue_len: int, ollama_up: bool, usage: dict):
    """Écrit data/status.json — lisible depuis GitHub pour visibilité mobile."""
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    completed = []
    if COMPLETED_FILE.exists():
        try:
            completed = json.loads(COMPLETED_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    remaining = load_tasks()
    status = {
        "session_id":      session_id,
        "cycle":           cycle,
        "updated_at":      datetime.utcnow().isoformat(),
        "last_task":       task[:120],
        "last_verdict":    verdict,
        "queue_remaining": len(remaining),
        "queue_preview":   [t[:80] for t in remaining[:3]],
        "completed_total": len(completed),
        "last_completed":  completed[-3:] if completed else [],
        "ollama_up":       ollama_up,
        "api_calls":       usage,
    }
    STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_autonomous_task(llm: LLMClient, store: MemoryStore, goal: str) -> tuple[str, bool]:
    """Le système génère lui-même sa prochaine tâche."""
    memory = store.retrieve_relevant(goal, max_results=5)
    prompt = SELF_TASK_SYSTEM.format(goal=goal, memory=memory)
    raw = llm.call(
        "Tu es un planificateur autonome. Génère la prochaine tâche en JSON.",
        prompt,
        task="plan",
    )
    import re
    raw = raw.strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            data = json.loads(m.group())
            return data.get("task", goal), data.get("needs_web", False)
        except Exception:
            pass
    return goal, False


def save_progress(session_id: str, cycle: int, stats: dict):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    prog = {
        "session_id":  session_id,
        "cycle":       cycle,
        "timestamp":   datetime.utcnow().isoformat(),
        "mea_stats":   stats,
    }
    PROGRESS_FILE.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")


def _maybe_run_cpg_tuning(store: "MemoryStore", cycle: int) -> bool:
    """
    Déclenche un tuning CPG si suffisamment d'échecs de simulation sont détectés.
    S'exécute tous les CPG_TUNING_INTERVAL cycles.
    Retourne True si le tuning a été exécuté.
    """
    CPG_TUNING_INTERVAL   = 5   # vérifie tous les N cycles
    SIM_FAILURE_THRESHOLD = 2   # seuil d'échecs avant déclenchement

    if cycle % CPG_TUNING_INTERVAL != 0:
        return False

    try:
        stats = store.stats()
        failures = sum(
            1 for e in store.all_entries()
            if getattr(e, "type", "") == "sim_failure"
        ) if hasattr(store, "all_entries") else 0

        # Fallback : cherche dans les entrées récentes via retrieve
        if failures == 0:
            recent = store.retrieve_relevant("sim_failure robot chute fallen", max_results=10)
            failures = recent.count("sim_failure")

        if failures < SIM_FAILURE_THRESHOLD:
            return False

        logger.info(f"[Continuous] {failures} sim_failures détectés — lancement CPG tuner...")

        from askio1.simulation.cpg_tuner import CPGTuner
        tuner  = CPGTuner(proto="proto1_tripod", sim_duration=3.0, n_random=5, n_hillclimb=8)
        result = tuner.tune(seed=cycle)
        out    = tuner.save_result(result, save_mea=True)

        logger.info(
            f"[CPGTuner] score={result.best_score} "
            f"dist={result.best_distance_m}m "
            f"falls={result.best_falls} "
            f"→ {out.name}"
        )
        return True

    except Exception as e:
        logger.warning(f"[CPGTuner] échec non bloquant : {e}")
        return False


def run_continuous(goal: str = "Développer un système cognitif autonome",
                   interval: int = 5,
                   max_cycles: int = 0):
    config   = load_config()
    llm      = LLMClient(config)
    store    = MemoryStore(config)
    observer = Observer(llm, store)
    thinker  = Thinker(llm)
    executor = Executor(llm, store)
    reviewer = Reviewer(llm)
    mem_agent= MemoryAgent(llm, store)
    searcher = WebSearchAgent(llm, store)
    cloop    = CognitiveLoop(store, llm)

    # Heartbeat Ollama
    ollama_cfg  = config.get("llm", {})
    heartbeat   = HeartbeatMonitor(
        ollama_host  = ollama_cfg.get("ollama_host",  "http://localhost:11434"),
        ollama_model = ollama_cfg.get("ollama_model", "qwen2.5:7b"),
    )
    heartbeat.start()

    session_id  = f"continuous_{datetime.now().strftime('%H%M%S')}"
    session_log = []
    cycle       = 0
    _shutdown   = [False]

    def handle_signal(sig, frame):
        logger.info("\n[Continuous] signal reçu — arrêt propre en cours...")
        _shutdown[0] = True

    signal.signal(signal.SIGINT,  handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info("=" * 60)
    logger.info(f"ASKIO1 v2 — MODE CONTINU — {session_id}")
    logger.info(f"Objectif : {goal}")
    logger.info(f"Modèle   : {llm._default_model} + Ollama={llm._ollama.model}")
    logger.info("=" * 60)

    cold_ctx = cloop.cold_start()
    if cold_ctx:
        logger.info(f"[ColdStart] contexte chargé ({len(cold_ctx)} chars)")

    while not _shutdown[0]:
        if max_cycles > 0 and cycle >= max_cycles:
            logger.info(f"[Continuous] max_cycles={max_cycles} atteint")
            break

        cycle += 1

        # ── Récupère ou génère la tâche ───────────────────────────────────
        task = pop_task()
        needs_web = False
        if task is None:
            task, needs_web = generate_autonomous_task(llm, store, goal)
            logger.info(f"[Cycle {cycle}] TÂCHE AUTONOME : {task[:100]}")
        else:
            needs_web = any(w in task.lower() for w in ("recherche", "web", "internet", "actualité", "news"))
            logger.info(f"[Cycle {cycle}] TÂCHE QUEUE : {task[:100]}")

        # ── Recherche web si nécessaire ───────────────────────────────────
        web_ctx = ""
        if needs_web:
            logger.info(f"[Cycle {cycle}] → WebSearch : {task[:60]}")
            web_result = searcher.search(task, save_to_memory=True)
            web_ctx = f"\n[RECHERCHE WEB]\n{web_result.get('summary', '')}\nFaits : {'; '.join(web_result.get('key_facts', [])[:3])}"

        # ── Cycle cognitif ────────────────────────────────────────────────
        adaptive_ctx = cloop.cycle_start(cycle, task)
        obs  = observer.observe(raw_text=task + web_ctx, context={"cycle": cycle, "session": session_id})
        snippets = store.retrieve_relevant(task)
        enriched = "\n\n".join(filter(None, [adaptive_ctx, web_ctx, f"[MEA]\n{snippets}"]))
        plan     = thinker.plan({"mission_id": session_id, "goal": goal[:100]}, task, enriched)
        result   = executor.execute(plan=plan, context={"cycle": cycle})
        review   = reviewer.review(result=result, goal=task, context={"cycle": cycle})
        verdict  = review.get("verdict", "?") if isinstance(review, dict) else "?"
        issues   = review.get("issues", []) if isinstance(review, dict) else []

        mem_agent.build_entries(observer_output=obs, context={"cycle": cycle})
        consolidated = cloop.cycle_end(cycle, verdict, issues, len(obs.get("candidates_for_memory", [])))

        # Usage LLM
        usage = llm.usage_stats()
        hb    = heartbeat.report()

        logger.info(
            f"[Cycle {cycle}] verdict={verdict} | "
            f"web={'oui' if needs_web else 'non'} | "
            f"ollama={hb['ollama_up']} ({hb['uptime_pct']}%) | "
            f"calls=anthropic:{usage['anthropic']} local:{usage['ollama']}"
        )

        session_log.append({
            "cycle": cycle, "task": task, "verdict": verdict,
            "needs_web": needs_web, "consolidated": consolidated,
        })

        save_progress(session_id, cycle, store.stats())
        log_completed_task(task, verdict, cycle)
        write_status(session_id, cycle, task, verdict,
                     len(load_tasks()), hb["ollama_up"], usage)

        # Tuning CPG automatique si des échecs de simulation sont détectés
        _maybe_run_cpg_tuning(store, cycle)

        if _shutdown[0]:
            break

        time.sleep(interval)

    # ── Arrêt propre ──────────────────────────────────────────────────────────
    logger.info(f"\n[Continuous] arrêt — {cycle} cycles effectués")
    heartbeat.stop()

    if cycle > 0:
        mem_agent.reflect(mission_id=session_id)
        cloop.session_end(session_id, session_log)

        # Génération automatique du compte-rendu quotidien
        try:
            from journal.generate_daily import generate_report, save_report
            logger.info("[Continuous] génération compte-rendu quotidien...")
            report = generate_report()
            report_path = save_report(report)
            logger.info(f"[Continuous] compte-rendu : {report_path}")
        except Exception as e:
            logger.warning(f"[Continuous] compte-rendu échoué (non bloquant) : {e}")

    usage = llm.usage_stats()
    logger.info(f"Usage total — anthropic={usage['anthropic']} ollama={usage['ollama']} errors={usage['errors']}")
    logger.info(f"Log : {LOG_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Askio1 v2 — mode continu")
    parser.add_argument("--goal",      default="Développer un système cognitif autonome capable de contrôler un robot 3D imprimable", help="Objectif global")
    parser.add_argument("--interval",  type=int, default=5,  help="Pause entre cycles (sec)")
    parser.add_argument("--max-cycles",type=int, default=0,  help="0 = infini")
    args = parser.parse_args()

    run_continuous(
        goal      = args.goal,
        interval  = args.interval,
        max_cycles= args.max_cycles,
    )
