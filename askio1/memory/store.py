"""
store.py — Persistance de la MEA (Mémoire Externe Auto-construite)
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .schemas import MemoryEntry, MissionState

logger = logging.getLogger(__name__)


class MemoryStore:

    def __init__(self, config: dict):
        base = config.get("memory", {}).get("long_term_dir", "data/memory/long_term")
        self.base_dir = Path(base)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_entry(self, entry: MemoryEntry) -> None:
        path = self.base_dir / f"{entry.id}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(entry.__dict__, f, ensure_ascii=False, indent=2)
        logger.debug(f"[MemoryStore] saved entry {entry.id}")

    def load_entry(self, entry_id: str) -> Optional[MemoryEntry]:
        path = self.base_dir / f"{entry_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return MemoryEntry(**data)

    def list_entries(self) -> List[MemoryEntry]:
        entries = []
        for p in self.base_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                entries.append(MemoryEntry(**data))
            except Exception as e:
                logger.warning(f"[MemoryStore] skip {p.name}: {e}")
        return entries

    def retrieve_relevant(self, query: str, max_results: int = 5) -> str:
        """Recherche simple par mots-clés dans les entrées LTM."""
        entries = self.list_entries()
        query_words = set(query.lower().split())
        scored = []
        for e in entries:
            text = f"{e.summary} {e.details}".lower()
            score = sum(1 for w in query_words if w in text)
            if score > 0:
                scored.append((score, e))
        scored.sort(reverse=True, key=lambda x: x[0])
        results = [e for _, e in scored[:max_results]]
        if not results:
            return "(aucune mémoire pertinente)"
        return "\n".join(f"[{e.type}/{e.scope}] {e.summary}" for e in results)

    def save_mission_state(self, state: MissionState) -> None:
        path = self.base_dir.parent / f"mission_{state.mission_id}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(state.__dict__, f, ensure_ascii=False, indent=2)

    def load_mission_state(self, mission_id: str) -> Optional[MissionState]:
        path = self.base_dir.parent / f"mission_{mission_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return MissionState(**data)
