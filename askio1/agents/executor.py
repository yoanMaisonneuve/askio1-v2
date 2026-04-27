"""
executor.py — Agent Exécuteur
Agit, génère du code, appelle des outils.
"""
import logging
import time
from askio1.tools.llm_client import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es l'Exécuteur d'un système cognitif.
À partir d'un plan, génère le code, les scripts ou les actions nécessaires.
Sois précis, concis, et immédiatement utilisable."""

MAX_RETRIES = 2
RETRY_DELAY = 2.0  # secondes


class Executor:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def execute(self, plan: dict, context: dict) -> str:
        user_prompt = f"Plan: {plan}\nContexte: {context}"
        last_error = None

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

        # Fallback gracieux — retourne un résumé du plan plutôt que de planter
        fallback = self._plan_to_text(plan)
        logger.error(f"[Executor] toutes les tentatives épuisées. Fallback: {fallback[:80]}")
        return f"[EXECUTOR FALLBACK — erreur: {last_error}]\n\n{fallback}"

    def _plan_to_text(self, plan: dict) -> str:
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
