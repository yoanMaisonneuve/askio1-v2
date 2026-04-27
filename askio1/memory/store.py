"""
store.py — MemoryStore v2 (Phase 2)
=====================================
Backend branché sur mea_core.py.

Changements vs v1 :
  - Sauvegarde via mea_core.MemoryEntry (scoring, decay, traçabilité, SHA256)
  - retrieve_relevant() classé par importance * pertinence_mots_clés
  - Decay appliqué au chargement → les entrées vieilles descendent naturellement
  - Backward compat : les agents continuent de passer des schemas.MemoryEntry simples
    → bridge automatique via _bridge_to_mea()

Architecture :
  schemas.MemoryEntry (agent)
      ↓ _bridge_to_mea()
  mea_core.MemoryEntry (stocké sur disque, avec scoring + decay)
      ↓ retrieve_relevant() → classement par score_final
  str (contexte injecté dans le Penseur)
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .schemas import MemoryEntry as SchemaEntry, MissionState
from .mea_core import (
    MemoryEntry as MeaEntry,
    ImportanceMetadata,
    ImportanceScorer,
    DecayManager,
)

logger = logging.getLogger(__name__)


# ─── Importance par niveau déclaré dans schemas ──────────────────────────────
IMPORTANCE_MAP = {
    "low":      0.2,
    "medium":   0.5,
    "high":     0.8,
    "critical": 1.0,
}

# ─── Half-life par type de mémoire (secondes) ────────────────────────────────
HALFLIFE_MAP = {
    "fact":       3 * 86400,    # 3 jours
    "rule":       7 * 86400,    # 7 jours
    "decision":   14 * 86400,   # 14 jours
    "experiment": 7 * 86400,
    "pattern":    30 * 86400,   # 1 mois
    "invariant":  365 * 86400,  # 1 an
}


class MemoryStore:
    """
    Store MEA v2 — persistance JSON + scoring multi-critères + decay.
    """

    def __init__(self, config: dict):
        base = config.get("memory", {}).get("long_term_dir", "data/memory/long_term")
        self.base_dir = Path(base)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.scorer   = ImportanceScorer(scoring_mode="weighted")
        logger.info(f"[MemoryStore v2] init → {self.base_dir}")

    # ─── Écriture ─────────────────────────────────────────────────────────

    def save_entry(self, entry: SchemaEntry) -> None:
        """Reçoit un schemas.MemoryEntry, le convertit en mea_core et persiste."""
        mea = self._bridge_to_mea(entry)
        mea.log_access("write", "save_entry")
        mea.update_importance(time.time())

        path = self.base_dir / f"{mea.id}.json"
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(mea.to_dict(), f, ensure_ascii=False, indent=2)
            logger.debug(f"[MemoryStore] ✓ {mea.id} [{entry.type}/{entry.scope}] importance={mea.current_importance:.3f}")
        except Exception as e:
            logger.error(f"[MemoryStore] ✗ save {mea.id}: {e}")

    # ─── Lecture ──────────────────────────────────────────────────────────

    def load_entry(self, entry_id: str) -> Optional[SchemaEntry]:
        path = self.base_dir / f"{entry_id}.json"
        if not path.exists():
            return None
        mea = self._load_mea(path)
        if mea:
            mea.log_access("read", "load_entry")
            self._resave_mea(mea, path)
        return self._mea_to_schema(mea) if mea else None

    def list_entries(self) -> List[SchemaEntry]:
        results = []
        for p in self.base_dir.glob("*.json"):
            mea = self._load_mea(p)
            if mea:
                results.append(self._mea_to_schema(mea))
        return results

    # ─── Retrieval intelligent ────────────────────────────────────────────

    def retrieve_relevant(self, query: str, max_results: int = 5) -> str:
        """
        Classe les entrées par score_final = importance_courante × pertinence_mots_clés.
        Applique le decay au chargement → les vieilles entrées descendent seules.
        """
        now = time.time()
        query_words = set(query.lower().split())
        scored: List[Tuple[float, MeaEntry]] = []

        for p in self.base_dir.glob("*.json"):
            mea = self._load_mea(p)
            if not mea:
                continue

            # Decay à jour
            mea.update_importance(now)

            # Pertinence mots-clés
            content_str = json.dumps(mea.content, ensure_ascii=False, default=str).lower()
            kw_hits = sum(1 for w in query_words if w in content_str)
            kw_score = min(1.0, kw_hits / max(len(query_words), 1))

            # Score final : importance vivante × pertinence
            final = mea.current_importance * 0.6 + kw_score * 0.4
            if final > 0.01:
                scored.append((final, mea))

        scored.sort(reverse=True, key=lambda x: x[0])
        top = [mea for _, mea in scored[:max_results]]

        if not top:
            return "(aucune mémoire pertinente)"

        lines = []
        for mea in top:
            c = mea.content
            type_  = c.get("type",    "?") if isinstance(c, dict) else "?"
            scope_ = c.get("scope",   "?") if isinstance(c, dict) else "?"
            summ_  = c.get("summary", str(c)[:80]) if isinstance(c, dict) else str(c)[:80]
            imp    = mea.current_importance
            lines.append(f"[{type_}/{scope_}|imp={imp:.2f}] {summ_}")

        logger.debug(f"[MemoryStore] retrieve '{query[:40]}' → {len(top)} résultats")
        return "\n".join(lines)

    # ─── MissionState (inchangé) ──────────────────────────────────────────

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

    # ─── Stats MEA ────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Retourne un résumé de l'état de la MEA."""
        now = time.time()
        entries = list(self.base_dir.glob("*.json"))
        importances = []
        types = {}
        for p in entries:
            mea = self._load_mea(p)
            if not mea:
                continue
            mea.update_importance(now)
            importances.append(mea.current_importance)
            t = mea.content.get("type", "?") if isinstance(mea.content, dict) else "?"
            types[t] = types.get(t, 0) + 1

        return {
            "total_entries":    len(entries),
            "avg_importance":   round(sum(importances) / len(importances), 3) if importances else 0,
            "max_importance":   round(max(importances), 3) if importances else 0,
            "min_importance":   round(min(importances), 3) if importances else 0,
            "types":            types,
        }

    # ─── Helpers privés ───────────────────────────────────────────────────

    def _bridge_to_mea(self, entry: SchemaEntry) -> MeaEntry:
        """Convertit un schemas.MemoryEntry → mea_core.MemoryEntry."""
        priority = IMPORTANCE_MAP.get(entry.importance, 0.5)
        half_life = HALFLIFE_MAP.get(entry.type, 7 * 86400)
        now = time.time()

        meta = ImportanceMetadata(
            user_priority     = priority,
            decision_impact   = priority,
            contextual_relevance = 0.5,
            recency_score     = 1.0,   # neuf à la création
            access_frequency  = 0.0,
        )

        content = {
            "type":       entry.type,
            "scope":      entry.scope,
            "summary":    entry.summary,
            "details":    entry.details,
            "links":      entry.links,
            "importance": entry.importance,
            "context":    entry.context,
        }

        return MeaEntry(
            id                = entry.id,
            content           = content,
            created_at        = now,
            updated_at        = now,
            importance_metadata = meta,
            decay_half_life   = half_life,
            is_external       = True,
            system_id         = "ASKIO1_V2",
        )

    def _mea_to_schema(self, mea: MeaEntry) -> SchemaEntry:
        """Convertit mea_core.MemoryEntry → schemas.MemoryEntry (compat agents)."""
        c = mea.content if isinstance(mea.content, dict) else {"summary": str(mea.content)}
        return SchemaEntry(
            id          = mea.id,
            type        = c.get("type",       "fact"),
            scope       = c.get("scope",      "mission"),
            context     = c.get("context",    {}),
            summary     = c.get("summary",    ""),
            details     = c.get("details",    ""),
            links       = c.get("links",      []),
            importance  = c.get("importance", "medium"),
            created_at  = datetime.fromtimestamp(mea.created_at).isoformat(),
            last_used_at= datetime.fromtimestamp(mea.updated_at).isoformat(),
            usage_count = len(mea.access_logs),
        )

    def _load_mea(self, path: Path) -> Optional[MeaEntry]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))

            # ── Détection format v1 (schemas.MemoryEntry, avant Phase 2) ──────
            if "type" in data and "importance_metadata" not in data:
                logger.debug(f"[MemoryStore] migration v1→v2 : {path.name}")
                schema_entry = SchemaEntry(
                    id          = data.get("id", path.stem),
                    type        = data.get("type", "fact"),
                    scope       = data.get("scope", "mission"),
                    context     = data.get("context", {}),
                    summary     = data.get("summary", ""),
                    details     = data.get("details", ""),
                    links       = data.get("links", []),
                    importance  = data.get("importance", "medium"),
                    created_at  = data.get("created_at", ""),
                )
                mea = self._bridge_to_mea(schema_entry)
                self._resave_mea(mea, path)   # réécriture en format v2
                return mea

            # ── Format v2 (mea_core.MemoryEntry) ─────────────────────────────
            im_data = data.pop("importance_metadata", {})
            im_data.pop("weights", None)
            logs_data = data.pop("access_logs", [])
            data.pop("checksum", None)

            from .mea_core import AccessLog
            entry = MeaEntry(**data, importance_metadata=ImportanceMetadata(**im_data))
            entry.access_logs = [AccessLog(**l) for l in logs_data]
            return entry
        except Exception as e:
            logger.warning(f"[MemoryStore] load error {path.name}: {e}")
            return None

    def _resave_mea(self, mea: MeaEntry, path: Path) -> None:
        """Sauvegarde silencieuse après mise à jour des accès/importance."""
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(mea.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"[MemoryStore] resave failed {path.name}: {e}")
