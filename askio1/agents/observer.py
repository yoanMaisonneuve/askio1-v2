"""
observer.py — Agent Observer
Lit, collecte, extrait des candidats pour la mémoire.
"""
import logging
from askio1.tools.llm_client import LLMClient
from askio1.memory.store import MemoryStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es l'Observer d'un système cognitif multi-agent.
Tu lis le texte fourni et tu extrais :
1. Un résumé concis
2. Des candidats pour la mémoire (règles, faits, patterns, décisions, invariants)

Réponds en JSON :
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


class Observer:
    def __init__(self, llm: LLMClient, memory: MemoryStore):
        self.llm    = llm
        self.memory = memory

    def observe(self, raw_text: str, context: dict) -> dict:
        import json
        user_prompt = f"Contexte: {context}\n\nTexte à analyser:\n{raw_text}"
        raw = self.llm.call(SYSTEM_PROMPT, user_prompt)
        try:
            return json.loads(raw)
        except Exception:
            return {"summary": raw, "candidates_for_memory": []}
