"""
reviewer.py — Agent Réviseur
Évalue, critique, corrige, stabilise.
"""
import json
import logging
from askio1.tools.llm_client import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es le Réviseur d'un système cognitif.
Évalue le résultat obtenu par rapport à l'objectif.

Réponds en JSON :
{
  "verdict": "success|failure|partial|uncertain",
  "issues": ["problème 1", ...],
  "suggestions": ["suggestion 1", ...]
}"""


class Reviewer:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def review(self, result: str, goal: str, context: dict) -> dict:
        user_prompt = f"Objectif: {goal}\nContexte: {context}\nRésultat:\n{result}"
        raw = self.llm.call(SYSTEM_PROMPT, user_prompt)
        try:
            return json.loads(raw)
        except Exception:
            return {"verdict": "uncertain", "issues": [raw], "suggestions": []}
