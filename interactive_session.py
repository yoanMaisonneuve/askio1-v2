"""
interactive_session.py — Interface Interactive Askio1 v2 (Phase 4a)
====================================================================
Boucle de conversation en temps réel avec toute l'infrastructure Phase 3.

Commandes spéciales :
  /quit ou /exit  — Termine la session + résumé final
  /stats          — Affiche les stats MEA courantes
  /memory <query> — Requête directe dans la MEA
  /help           — Liste des commandes

Usage :
    cd askio1_v2
    python interactive_session.py
"""

import json
import logging
import sys
import time
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

# ─── Logging — fichier seulement, stdout propre ───────────────────────────────
Path("data/logs").mkdir(parents=True, exist_ok=True)
LOG_FILE = f"data/logs/interactive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s — %(message)s"))
logging.basicConfig(level=logging.DEBUG, handlers=[file_handler])
logger = logging.getLogger("askio1.interactive")


# ─── UI helpers ───────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
BLUE   = "\033[34m"
MAGENTA= "\033[35m"

def banner():
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════════════╗
║          ASKIO1 v2 — Système Cognitif Interactif         ║
║          Phase 4a · MEA active · Boucle cognitive        ║
╚══════════════════════════════════════════════════════════╝{RESET}
{DIM}Tapez votre question, ou /help pour les commandes.{RESET}
""")

def print_thinking():
    sys.stdout.write(f"{DIM}⟳  Traitement en cours...{RESET}")
    sys.stdout.flush()

def clear_thinking():
    sys.stdout.write("\r" + " " * 40 + "\r")
    sys.stdout.flush()

def print_result(result: str, verdict: str, cycle: int, elapsed: float):
    color = GREEN if verdict == "success" else (YELLOW if verdict == "partial" else RED)
    print(f"\n{CYAN}─── Askio1 [cycle {cycle} · {elapsed:.1f}s · {color}{verdict}{CYAN}] ───{RESET}")
    print(result)
    print(f"{DIM}{'─' * 60}{RESET}\n")

def print_stats(store: MemoryStore, cloop: CognitiveLoop):
    stats = store.stats()
    perf  = cloop.stats.summary()
    print(f"\n{BOLD}📊 Stats MEA{RESET}")
    print(f"  Entrées totales : {stats['total_entries']}")
    print(f"  Importance moy  : {stats['avg_importance']}")
    print(f"  Types           : {stats['types']}")
    print(f"  Session — {perf['total_cycles']} cycles · {perf['success_rate']:.0%} succès · failure_rate={perf['failure_rate']:.0%}")
    print()

def print_memory(snippets: str):
    print(f"\n{BOLD}🧠 MEA — Entrées pertinentes{RESET}")
    print(snippets or "(aucune)")
    print()

def print_help():
    print(f"""
{BOLD}Commandes disponibles :{RESET}
  {CYAN}/quit{RESET} ou {CYAN}/exit{RESET}   — Terminer la session
  {CYAN}/stats{RESET}          — Stats MEA courantes
  {CYAN}/memory <query>{RESET} — Requête directe dans la mémoire
  {CYAN}/help{RESET}           — Cette aide
  {DIM}(Tout autre texte est envoyé au système cognitif){RESET}
""")

def print_session_end(session_id: str, log_file: str, cloop: CognitiveLoop, store: MemoryStore):
    stats = store.stats()
    perf  = cloop.stats.summary()
    print(f"\n{CYAN}{BOLD}╔══════════════════════════════════════════╗{RESET}")
    print(f"{CYAN}{BOLD}║  SESSION TERMINÉE — {session_id:20s}  ║{RESET}")
    print(f"{CYAN}{BOLD}╚══════════════════════════════════════════╝{RESET}")
    print(f"  Cycles          : {perf['total_cycles']}")
    print(f"  Taux succès     : {perf['success_rate']:.0%}")
    print(f"  Entrées MEA     : {stats['total_entries']}")
    print(f"  Log             : {log_file}")
    print()


# ─── Session ──────────────────────────────────────────────────────────────────

def load_config(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_interactive():
    config   = load_config()
    llm      = LLMClient(config)
    store    = MemoryStore(config)
    observer = Observer(llm, store)
    thinker  = Thinker(llm)
    executor = Executor(llm)
    reviewer = Reviewer(llm)
    mem_agent= MemoryAgent(llm, store)
    cloop    = CognitiveLoop(store, llm)

    session_id  = f"interactive_{datetime.now().strftime('%H%M%S')}"
    session_log = []
    cycle       = 0

    banner()

    # ── Cold start ────────────────────────────────────────────────────────────
    cold_ctx = cloop.cold_start()
    if cold_ctx:
        print(f"{MAGENTA}🔗 Mémoire cross-session chargée :{RESET}")
        # Afficher seulement le résumé, pas les règles brutes
        for line in cold_ctx.split("\n"):
            if "Résumé" in line or "Règles clés" in line:
                print(f"  {DIM}{line}{RESET}")
        print()
    else:
        print(f"{DIM}  Nouvelle session — aucun contexte précédent.{RESET}\n")

    logger.info(f"SESSION {session_id} démarrée")

    try:
        while True:
            try:
                user_input = input(f"{BOLD}Vous{RESET} › ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue

            # ── Commandes spéciales ───────────────────────────────────────────
            if user_input.lower() in ("/quit", "/exit"):
                break

            if user_input.lower() == "/help":
                print_help()
                continue

            if user_input.lower() == "/stats":
                print_stats(store, cloop)
                continue

            if user_input.lower().startswith("/memory"):
                query = user_input[7:].strip() or "système cognitif"
                snippets = store.retrieve_relevant(query, max_results=8)
                print_memory(snippets)
                continue

            # ── Cycle cognitif ────────────────────────────────────────────────
            cycle += 1
            t0 = time.time()

            print_thinking()
            logger.info(f"[Cycle {cycle}] INPUT: {user_input[:100]}")

            try:
                # Contexte adaptatif boucle courte
                adaptive_ctx = cloop.cycle_start(cycle, user_input)

                # Observer
                obs        = observer.observe(raw_text=user_input, context={"cycle": cycle, "session": session_id})
                candidates = obs.get("candidates_for_memory", [])

                # Penseur
                snippets = store.retrieve_relevant(user_input)
                enriched = f"{adaptive_ctx}\n\n[MEA]\n{snippets}" if adaptive_ctx else snippets
                plan     = thinker.plan({"mission_id": session_id}, user_input, enriched)

                # Exécuteur
                result = executor.execute(plan=plan, context={"cycle": cycle})

                # Réviseur
                review  = reviewer.review(result=result, goal=user_input, context={"cycle": cycle})
                verdict = review.get("verdict", "?") if isinstance(review, dict) else "?"
                issues  = review.get("issues", []) if isinstance(review, dict) else []

                # Mémoire
                mem_agent.build_entries(observer_output=obs, context={"cycle": cycle, "review": review})

                # Boucle courte — màj stats + triggers
                triggered = cloop.cycle_end(cycle, verdict, issues, len(candidates))

            except Exception as e:
                clear_thinking()
                print(f"\n{RED}⚠  Erreur au cycle {cycle} : {e}{RESET}\n")
                logger.error(f"[Cycle {cycle}] ERREUR: {e}", exc_info=True)
                continue

            elapsed = time.time() - t0
            clear_thinking()
            print_result(result, verdict, cycle, elapsed)

            if triggered:
                print(f"{MAGENTA}  🔁 Consolidation MEA déclenchée (cycle {cycle}){RESET}\n")

            logger.info(f"[Cycle {cycle}] verdict={verdict} elapsed={elapsed:.1f}s consolidation={triggered}")

            session_log.append({
                "cycle":   cycle,
                "input":   user_input,
                "result":  result,
                "verdict": verdict,
                "issues":  issues,
            })

    finally:
        # ── Boucle longue : fin de session ────────────────────────────────────
        if cycle > 0:
            logger.info("[BoucleLongue] Sauvegarde résumé cross-session...")
            mem_agent.reflect(mission_id=session_id)
            cloop.session_end(session_id=session_id, session_log=session_log)

            json_log = LOG_FILE.replace(".log", "_structured.json")
            with open(json_log, "w", encoding="utf-8") as f:
                json.dump(session_log, f, ensure_ascii=False, indent=2)

            print_session_end(session_id, LOG_FILE, cloop, store)
        else:
            print(f"\n{DIM}Session vide — rien à sauvegarder.{RESET}\n")


if __name__ == "__main__":
    run_interactive()
