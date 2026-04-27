"""
cognitive_loop.py — Boucle Cognitive Askio1 v2 (Phase 3)
=========================================================
Deux boucles :

  BOUCLE COURTE (intra-session)
  ──────────────────────────────
  À chaque cycle, le CognitiveLoop :
    1. Reçoit le résultat du Réviseur (verdict + issues)
    2. Met à jour un état de performance glissant (WindowStats)
    3. Adapte dynamiquement le prompt de contexte injecté dans le Penseur
    4. Déclenche un trigger de consolidation si le taux d'échec dépasse le seuil

  BOUCLE LONGUE (cross-session)
  ──────────────────────────────
    - Au démarrage : charge le résumé MEA le plus récent depuis le disque (cold start)
    - À la fin     : génère un résumé de session et le persiste comme entrée "invariant"

  TRIGGERS DE CONSOLIDATION
  ──────────────────────────
    - Seuil d'échec (failure_rate > 0.4 sur fenêtre glissante)
    - Seuil de saturation (> N entrées LTM depuis le début de session)
    - Trigger temporel (toutes les K cycles)
"""

import json
import logging
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

from askio1.memory.store import MemoryStore
from askio1.memory.schemas import MemoryEntry

logger = logging.getLogger(__name__)


# ─── Paramètres ──────────────────────────────────────────────────────────────
WINDOW_SIZE        = 5      # cycles pour le calcul du taux d'échec
FAILURE_THRESHOLD  = 0.4    # déclanche consolidation si failure_rate > seuil
SATURATION_LIMIT   = 30     # entrées créées dans la session avant consolidation forcée
PERIODIC_TRIGGER   = 3      # consolidation toutes les K cycles
RESUME_FILE        = "data/memory/session_resume.json"


class WindowStats:
    """Statistiques glissantes sur une fenêtre de N cycles."""

    def __init__(self, size: int = WINDOW_SIZE):
        self._verdicts: deque = deque(maxlen=size)
        self.total_cycles = 0

    def record(self, verdict: str) -> None:
        self._verdicts.append(verdict)
        self.total_cycles += 1

    @property
    def failure_rate(self) -> float:
        if not self._verdicts:
            return 0.0
        failures = sum(1 for v in self._verdicts if v in ("failure", "partial"))
        return failures / len(self._verdicts)

    @property
    def success_rate(self) -> float:
        return 1.0 - self.failure_rate

    def summary(self) -> dict:
        return {
            "total_cycles": self.total_cycles,
            "window":       list(self._verdicts),
            "failure_rate": round(self.failure_rate, 2),
            "success_rate": round(self.success_rate, 2),
        }


class CognitiveLoop:
    """
    Gestionnaire de la boucle cognitive courte + longue.
    Usage :
        loop = CognitiveLoop(store, llm)
        loop.cold_start()                          # charge mémoire cross-session
        ctx = loop.cycle_start(cycle_n, task)      # contexte adaptatif → injecté dans Thinker
        loop.cycle_end(cycle_n, verdict, issues)   # màj stats + triggers
        loop.session_end(session_id, log)          # boucle longue : résumé persisté
    """

    def __init__(self, store: MemoryStore, llm=None):
        self.store   = store
        self.llm     = llm   # optionnel — requis uniquement pour la réflexion LLM
        self.stats   = WindowStats()
        self.session_entries_count = 0   # entrées créées depuis le début de session
        self._last_consolidation   = 0   # cycle du dernier trigger
        self._cold_context: str    = ""  # résumé cross-session chargé au démarrage
        self._cycle_log: list      = []  # log léger des cycles pour session_end

    # ─── Boucle longue : démarrage ────────────────────────────────────────

    def cold_start(self) -> str:
        """
        Charge le résumé MEA de la session précédente.
        Retourne une chaîne de contexte injectée dans le 1er cycle du Penseur.
        """
        path = Path(RESUME_FILE)
        if not path.exists():
            logger.info("[CognitiveLoop] cold start — aucun résumé précédent")
            self._cold_context = ""
            return ""

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            session_id = data.get("session_id", "?")
            summary    = data.get("summary", "")
            rules      = data.get("top_rules", [])
            ts         = data.get("timestamp", "")
            logger.info(f"[CognitiveLoop] cold start — résumé session {session_id} ({ts})")
            ctx = (
                f"[MÉMOIRE CROSS-SESSION — session {session_id}]\n"
                f"Résumé : {summary}\n"
                f"Règles clés : {'; '.join(rules[:3]) if rules else 'aucune'}"
            )
            self._cold_context = ctx
            return ctx
        except Exception as e:
            logger.warning(f"[CognitiveLoop] erreur cold start : {e}")
            self._cold_context = ""
            return ""

    # ─── Boucle courte : par cycle ────────────────────────────────────────

    def cycle_start(self, cycle: int, task: str) -> str:
        """
        Construit le contexte adaptatif à injecter dans le Penseur.
        Inclut :
          - résumé cross-session (cycle 1 seulement)
          - stats de performance glissantes
          - message d'alerte si failure_rate élevé
        """
        parts = []

        # Cross-session (uniquement cycle 1)
        if cycle == 1 and self._cold_context:
            parts.append(self._cold_context)

        # Stats courantes
        stats = self.stats.summary()
        if stats["total_cycles"] > 0:
            parts.append(
                f"[PERFORMANCE SESSION] cycles={stats['total_cycles']} "
                f"succès={stats['success_rate']:.0%} "
                f"fenêtre={stats['window']}"
            )

        # Alerte adaptation
        if self.stats.failure_rate > FAILURE_THRESHOLD:
            parts.append(
                "⚠️  ALERTE : taux d'échec élevé sur les derniers cycles. "
                "Sois plus prudent, décompose davantage, vérifie tes hypothèses."
            )

        context = "\n".join(parts) if parts else ""
        logger.debug(f"[CognitiveLoop] cycle {cycle} — contexte adaptatif ({len(context)} chars)")
        return context

    def cycle_end(self, cycle: int, verdict: str, issues: list, entries_added: int = 0) -> bool:
        """
        Met à jour les stats et décide si un trigger de consolidation doit se déclencher.
        Retourne True si la consolidation a été déclenchée.
        """
        self.stats.record(verdict)
        self.session_entries_count += entries_added
        self._cycle_log.append({
            "cycle":   cycle,
            "verdict": verdict,
            "issues":  issues[:2],   # tronqué pour le log
        })

        triggered = self._check_triggers(cycle)
        logger.info(
            f"[CognitiveLoop] cycle {cycle} — verdict={verdict} "
            f"failure_rate={self.stats.failure_rate:.0%} "
            f"LTM_session={self.session_entries_count} "
            f"consolidation={'OUI' if triggered else 'non'}"
        )
        return triggered

    def _check_triggers(self, cycle: int) -> bool:
        """Vérifie les 3 triggers de consolidation."""
        since_last = cycle - self._last_consolidation

        # Trigger 1 — taux d'échec
        if self.stats.failure_rate > FAILURE_THRESHOLD and since_last >= 2:
            logger.warning(f"[CognitiveLoop] TRIGGER failure_rate={self.stats.failure_rate:.0%}")
            self._consolidate(cycle, reason="failure_rate")
            return True

        # Trigger 2 — saturation LTM
        if self.session_entries_count >= SATURATION_LIMIT and since_last >= 2:
            logger.warning(f"[CognitiveLoop] TRIGGER saturation={self.session_entries_count}")
            self._consolidate(cycle, reason="saturation")
            return True

        # Trigger 3 — périodique
        if since_last >= PERIODIC_TRIGGER:
            logger.info(f"[CognitiveLoop] TRIGGER périodique (cycle {cycle})")
            self._consolidate(cycle, reason="periodic")
            return True

        return False

    def _consolidate(self, cycle: int, reason: str) -> None:
        """
        Consolidation légère sans LLM :
          - Calcule les stats de la MEA
          - Log un rapport de santé
          - (optionnel) appelle LLM si disponible pour méta-réflexion
        """
        self._last_consolidation = cycle
        stats = self.store.stats()
        logger.info(
            f"[CognitiveLoop] CONSOLIDATION [{reason}] — "
            f"total={stats['total_entries']} "
            f"avg_imp={stats['avg_importance']} "
            f"types={stats['types']}"
        )

        if self.llm:
            self._llm_consolidate(cycle, reason, stats)

    def _llm_consolidate(self, cycle: int, reason: str, stats: dict) -> None:
        """Réflexion LLM légère sur l'état de la MEA."""
        try:
            entries = self.store.list_entries()
            sample  = [
                {"type": e.type, "summary": e.summary[:80]}
                for e in entries[:15]
            ]
            prompt = (
                f"Cycle {cycle} — raison consolidation : {reason}\n"
                f"Stats MEA : {json.dumps(stats, ensure_ascii=False)}\n"
                f"Échantillon entrées : {json.dumps(sample, ensure_ascii=False)}\n\n"
                "En 2-3 phrases, identifie le pattern dominant et la règle la plus critique."
            )
            sys = (
                "Tu es le module de méta-cognition d'un système cognitif. "
                "Sois synthétique et actionnable. Réponds en texte libre, 3 lignes max."
            )
            insight = self.llm.call(sys, prompt)
            logger.info(f"[CognitiveLoop] insight consolidation : {insight[:300]}")

            # Persiste l'insight comme entrée "invariant" haute importance
            entry = MemoryEntry(
                id         = str(uuid.uuid4())[:8],
                type       = "invariant",
                scope      = "mission",
                context    = {"cycle": cycle, "trigger": reason},
                summary    = f"[AUTO-CONSOLIDATION cycle {cycle}] {insight[:120]}",
                details    = insight,
                links      = [],
                importance = "high",
                created_at = datetime.utcnow().isoformat(),
            )
            self.store.save_entry(entry)
            self.session_entries_count += 1
        except Exception as e:
            logger.warning(f"[CognitiveLoop] LLM consolidation error : {e}")

    # ─── Boucle longue : fin de session ───────────────────────────────────

    def session_end(self, session_id: str, session_log: list) -> None:
        """
        Génère un résumé de session et le persiste dans RESUME_FILE
        pour être rechargé à la prochaine session (cold start).
        """
        stats = self.store.stats()
        perf  = self.stats.summary()

        # Extraire les règles/invariants de la MEA
        entries  = self.store.list_entries()
        top_rules = [
            e.summary for e in entries
            if e.type in ("rule", "invariant", "pattern") and e.importance in ("high", "critical")
        ][:5]

        # Résumé narratif succinct
        verdicts  = [c["verdict"] for c in self._cycle_log]
        successes = verdicts.count("success")
        summary   = (
            f"{len(self._cycle_log)} cycles — {successes}/{len(self._cycle_log)} succès. "
            f"MEA : {stats['total_entries']} entrées, importance moy. {stats['avg_importance']}. "
            f"Failure rate session : {perf['failure_rate']:.0%}."
        )

        resume = {
            "session_id": session_id,
            "timestamp":  datetime.utcnow().isoformat(),
            "summary":    summary,
            "top_rules":  top_rules,
            "mea_stats":  stats,
            "perf":       perf,
        }

        Path(RESUME_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(RESUME_FILE).write_text(
            json.dumps(resume, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"[CognitiveLoop] résumé session persisté → {RESUME_FILE}")
        logger.info(f"[CognitiveLoop] résumé : {summary}")
