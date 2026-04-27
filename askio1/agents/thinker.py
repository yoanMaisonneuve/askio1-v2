"""
thinker.py — Agent Penseur
Raisonne, structure, planifie.
"""
import json
import logging
from askio1.tools.llm_client import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es le Penseur d'un système cognitif.
À partir de la mission, de la tâche et de la mémoire pertinente,
produis un plan d'action structuré.

Réponds en JSON :
{
  "steps": ["étape 1", "étape 2", ...],
  "hypotheses": ["hypothèse 1", ...],
  "variants_to_test": ["variante 1", ...]
}"""


class Thinker:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def plan(self, mission_state: dict, task: str, memory_snippets: str) -> dict:
        user_prompt = f"Mission: {mission_state}\nTâche: {task}\nMémoire pertinente:\n{memory_snippets}"
        raw = self.llm.call(SYSTEM_PROMPT, user_prompt)
        try:
            return json.loads(raw)
        except Exception:
            return {"steps": [raw], "hypotheses": [], "variants_to_test": []}
