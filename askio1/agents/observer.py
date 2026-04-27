"""
observer.py — Agent Observer
Lit, collecte, extrait des candidats pour la mémoire.
"""
import json
import logging
import re
from askio1.tools.llm_client import LLMClient
from askio1.memory.store import MemoryStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es l'Observer d'un système cognitif multi-agent.
Tu lis le texte fourni et tu extrais :
1. Un résumé concis
2. Des candidats pour la mémoire (règles, faits, patterns, décisions, invariants)

IMPORTANT : Réponds UNIQUEMENT en JSON brut, sans bloc markdown, sans ```json, sans texte avant ou après.
Format exact :
{
  "summary": "...",
  "candidates_for_memory": [
    {"type": "rule|fact|decision|experiment|pattern|invariant",
     "scope": "mission|module|robot|joint|vision|control",
     "summary": "...",
     "details": "...",
     "importance": "low|medium|high|critical"}
  ]
}"""


def _clean_json(raw: str) -> str:
    """Extrait le JSON d'une réponse qui peut contenir des blocs markdown."""
    raw = raw.strip()
    # Retirer ```json ... ``` ou ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if match:
        return match.group(1).strip()
    # Chercher le premier { ... } de niveau racine
    start = raw.find("{")
    end   = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end+1]
    return raw


class Observer:
    def __init__(self, llm: LLMClient, memory: MemoryStore):
        self.llm    = llm
        self.memory = memory

    def observe(self, raw_text: str, context: dict) -> dict:
        user_prompt = f"Contexte: {context}\n\nTexte à analyser:\n{raw_text}"
        raw = self.llm.call(SYSTEM_PROMPT, user_prompt)
        cleaned = _clean_json(raw)
        try:
            result = json.loads(cleaned)
            logger.debug(f"[Observer] parsed OK — {len(result.get('candidates_for_memory', []))} candidats")
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"[Observer] JSON parse failed: {e} — raw[:200]={raw[:200]}")
            return {"summary": raw, "candidates_for_memory": []}
