"""
executor.py — Agent Exécuteur (Phase 8)
========================================
Agit, génère du code, appelle des outils.

Phase 8 : détecte les CODE_TASK dans le plan et délègue
au ClaudeCodeAgent au lieu de générer du texte.

Routing :
  plan contient "CODE_TASK:" → ClaudeCodeAgent (code réel + artifact)
  sinon                      → LLM call standard (analyse, texte)
"""
import json
import logging
import time
from typing import Optional

from askio1.tools.llm_client import LLMClient
from askio1.memory.store import MemoryStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es l'Exécuteur d'un système cognitif.
À partir d'un plan, génère le code, les scripts ou les actions nécessaires.
Sois précis, concis, et immédiatement utilisable."""

MAX_RETRIES = 2
RETRY_DELAY = 2.0  # secondes


class Executor:
    def __init__(self, llm: LLMClient, store: Optional[MemoryStore] = None):
        self.llm   = llm
        self.store = store
        # Initialisation paresseuse du ClaudeCodeAgent
        self._code_agent = None

    def _get_code_agent(self):
        """Initialise ClaudeCodeAgent à la demande."""
        if self._code_agent is None:
            from askio1.agents.claude_code_agent import ClaudeCodeAgent
            self._code_agent = ClaudeCodeAgent(store=self.store)
        return self._code_agent

    def execute(self, plan: dict, context: dict) -> str:
        # ── Détection CODE_TASK ───────────────────────────────────────────────
        code_task = self._extract_code_task(plan)
        if code_task:
            task_desc, artifact_type = code_task
            logger.info(f"[Executor] CODE_TASK détecté [{artifact_type}] : {task_desc[:60]}")
            memory_context = ""
            if self.store:
                memory_context = self.store.retrieve_relevant(task_desc, max_results=3)
            result = self._get_code_agent().run(
                task=task_desc,
                artifact_type=artifact_type,
                memory_context=memory_context,
            )
            source = result.get("source", "?")
            path   = result.get("artifact_path", "")
            code   = result.get("code", "")
            return (
                f"[CODE_TASK — source={source}]\n"
                f"Artifact: {path}\n\n"
                f"{code[:2000]}{'...' if len(code) > 2000 else ''}"
            )

        # ── Exécution standard (LLM) ──────────────────────────────────────────
        user_prompt = f"Plan: {plan}\nContexte: {context}"
        last_error  = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = self.llm.call(SYSTEM_PROMPT, user_prompt)
                if result and result.strip():
                    if attempt > 1:
                        logger.info(f"[Executor] succès à la tentative {attempt}")
                    return result
                logger.warning(f"[Executor] réponse vide (tentative {attempt})")
            except Exception as e:
                last_error = e
                logger.warning(f"[Executor] erreur tentative {attempt}/{MAX_RETRIES}: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)

        # Fallback gracieux
        fallback = self._plan_to_text(plan)
        logger.error(f"[Executor] toutes les tentatives épuisées. Fallback: {fallback[:80]}")
        return f"[EXECUTOR FALLBACK — erreur: {last_error}]\n\n{fallback}"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_code_task(self, plan) -> Optional[tuple[str, str]]:
        """Délègue à claude_code_agent.extract_code_task."""
        try:
            from askio1.agents.claude_code_agent import extract_code_task
            return extract_code_task(plan)
        except Exception:
            return None

    def _plan_to_text(self, plan) -> str:
        """Extrait le texte du plan comme réponse de secours."""
        if not isinstance(plan, dict):
            return str(plan)
        steps = plan.get("steps", [])
        hyps  = plan.get("hypotheses", [])
        lines = ["Plan d'action :"]
        for i, s in enumerate(steps, 1):
            lines.append(f"  {i}. {s}")
        if hyps:
            lines.append("\nHypothèses :")
            for h in hyps[:3]:
                lines.append(f"  - {h}")
        return "\n".join(lines)
