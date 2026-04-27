"""
main.py — Orchestrateur principal Askio1 v2
============================================
Boucle cognitive : Observer → Penseur → Exécuteur → Réviseur → Mémoire
"""
import logging
from pathlib import Path

import yaml
from dotenv import load_dotenv

from askio1.agents.observer import Observer
from askio1.agents.thinker import Thinker
from askio1.agents.executor import Executor
from askio1.agents.reviewer import Reviewer
from askio1.agents.memory_agent import MemoryAgent
from askio1.memory.store import MemoryStore
from askio1.tools.llm_client import LLMClient
from askio1.tools.logging_utils import setup_logging

load_dotenv()


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run(task: str, mission_id: str = "default"):
    config = load_config()
    setup_logging(config.get("llm", {}).get("log_level", "INFO"))
    logger = logging.getLogger("askio1.orchestrator")

    # Initialisation des composants
    llm = LLMClient(config)
    store = MemoryStore(config)

    observer    = Observer(llm, store)
    thinker     = Thinker(llm)
    executor    = Executor(llm)
    reviewer    = Reviewer(llm)
    mem_agent   = MemoryAgent(llm, store)

    logger.info(f"[Askio1] Démarrage — mission={mission_id} · tâche='{task[:60]}'")

    cycle = 0
    while True:
        cycle += 1
        logger.info(f"[Cycle {cycle}] ---")

        # 1. Observer : collecter + candidats mémoire
        obs_output = observer.observe(raw_text=task, context={"cycle": cycle, "mission": mission_id})

        # 2. Penseur : planifier
        memory_snippets = store.retrieve_relevant(task)
        plan = thinker.plan(mission_state={}, task=task, memory_snippets=memory_snippets)

        # 3. Exécuteur : agir
        result = executor.execute(plan=plan, context={"cycle": cycle})

        # 4. Réviseur : évaluer
        review = reviewer.review(result=result, goal=task, context={"cycle": cycle})

        # 5. MemoryAgent : mémoriser
        mem_agent.build_entries(observer_output=obs_output, context={"cycle": cycle, "review": review})

        # Réflexion périodique
        if cycle % config["memory"]["reflection_interval"] == 0:
            mem_agent.reflect(mission_id=mission_id)

        logger.info(f"[Cycle {cycle}] verdict={review.get('verdict', 'unknown')}")

        # Critère d'arrêt (à adapter)
        if review.get("verdict") == "success":
            logger.info("[Askio1] Objectif atteint.")
            break

        user_input = input(f"\n[Cycle {cycle}] Continuer ? (Enter=oui / nouvelle tâche / 'exit') > ").strip()
        if user_input.lower() in ("exit", "quit", "stop"):
            break
        if user_input:
            task = user_input


if __name__ == "__main__":
    import sys
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Tâche initiale > ").strip()
    run(task=task)
