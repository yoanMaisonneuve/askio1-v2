"""
reviewer.py — Agent Réviseur
Évalue, critique, corrige, stabilise.
"""
import json
import logging
import re
from askio1.tools.llm_client import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es le Réviseur d'un système cognitif.
Évalue le résultat obtenu par rapport à l'objectif.

IMPORTANT : Réponds UNIQUEMENT en JSON brut, sans bloc markdown, sans ```json, sans texte avant ou après.
Format exact :
{
  "verdict": "success|failure|partial|uncertain",
  "issues": ["problème 1", ...],
  "suggestions": ["suggestion 1", ...]
}"""


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if match:
        return match.group(1).strip()
    start = raw.find("{")
    end   = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end+1]
    return raw


class Reviewer:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def review(self, result: str, goal: str, context: dict) -> dict:
        user_prompt = f"Objectif: {goal}\nContexte: {context}\nRésultat:\n{result}"
        raw = self.llm.call(SYSTEM_PROMPT, user_prompt)
        cleaned = _clean_json(raw)
        try:
            result_dict = json.loads(cleaned)
            logger.debug(f"[Reviewer] verdict={result_dict.get('verdict')}")
            return result_dict
        except json.JSONDecodeError as e:
            logger.warning(f"[Reviewer] JSON parse failed: {e}")
            return {"verdict": "uncertain", "issues": [raw], "suggestions": []}
