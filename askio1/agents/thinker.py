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

IMPORTANT : Réponds UNIQUEMENT en JSON brut, sans bloc markdown, sans ```json, sans texte avant ou après.
Format exact :
{
  "steps": ["étape 1", "étape 2", ...],
  "hypotheses": ["hypothèse 1", ...],
  "variants_to_test": ["variante 1", ...]
}"""


def _clean_json(raw: str) -> str:
    import re
    raw = raw.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if match:
        return match.group(1).strip()
    start = raw.find("{")
    end   = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end+1]
    return raw


class Thinker:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def plan(self, mission_state: dict, task: str, memory_snippets: str) -> dict:
        user_prompt = f"Mission: {mission_state}\nTâche: {task}\nMémoire pertinente:\n{memory_snippets}"
        raw = self.llm.call(SYSTEM_PROMPT, user_prompt)
        cleaned = _clean_json(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"steps": [raw], "hypotheses": [], "variants_to_test": []}
