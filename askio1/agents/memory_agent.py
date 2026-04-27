"""
memory_agent.py — Agent Mémoire (MEA)
Stocke, indexe, résume, élève, réfléchit.
"""
import json
import logging
import uuid
from datetime import datetime

from askio1.tools.llm_client import LLMClient
from askio1.memory.store import MemoryStore
from askio1.memory.schemas import MemoryEntry

logger = logging.getLogger(__name__)

REFLECT_SYSTEM = """Tu es le module de réflexion d'une mémoire externe auto-construite (MEA).
Tu reçois une liste d'entrées mémoire. Tu dois :
1. Fusionner les entrées redondantes
2. Élever le niveau d'abstraction (trouver des règles, patterns, invariants)
3. Identifier les contradictions
4. Proposer des méta-règles

Réponds en JSON : {"meta_rules": [...], "merged_ids": [...], "observations": "..."}"""


class MemoryAgent:
    def __init__(self, llm: LLMClient, store: MemoryStore):
        self.llm   = llm
        self.store = store

    def build_entries(self, observer_output: dict, context: dict):
        candidates = observer_output.get("candidates_for_memory", [])
        for c in candidates:
            entry = MemoryEntry(
                id          = str(uuid.uuid4())[:8],
                type        = c.get("type", "fact"),
                scope       = c.get("scope", "mission"),
                context     = context,
                summary     = c.get("summary", ""),
                details     = c.get("details", ""),
                links       = [],
                importance  = c.get("importance", "medium"),
                created_at  = datetime.utcnow().isoformat(),
            )
            self.store.save_entry(entry)
            logger.debug(f"[MemoryAgent] entry saved: {entry.id} [{entry.type}]")

    def reflect(self, mission_id: str):
        entries = self.store.list_entries()
        if not entries:
            return
        entries_text = json.dumps(
            [{"id": e.id, "type": e.type, "summary": e.summary} for e in entries[:30]],
            ensure_ascii=False
        )
        raw = self.llm.call(REFLECT_SYSTEM, f"Entrées mémoire:\n{entries_text}")
        logger.info(f"[MemoryAgent] réflexion terminée: {raw[:200]}")
