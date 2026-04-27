"""
web_search.py — WebSearchAgent (Phase 7)
=========================================
Agent de recherche web branché sur DuckDuckGo (pas de clé API).

Fonctionnement :
  1. Reçoit une requête en langage naturel
  2. Extrait 3-5 résultats DuckDuckGo (titre + snippet + url)
  3. Résume les trouvailles via le LLM local (Ollama si dispo, Haiku sinon)
  4. Retourne un résumé structuré + liste de sources
  5. Sauvegarde les faits pertinents dans la MEA

Intégration dans le pipeline :
  Le Penseur peut déléguer une étape au WebSearchAgent si le plan
  contient le mot-clé "recherche" ou "web" dans ses étapes.
"""

import json
import logging
import time
from typing import List, Optional

from askio1.tools.llm_client import LLMClient
from askio1.memory.store import MemoryStore
from askio1.memory.schemas import MemoryEntry

logger = logging.getLogger(__name__)

SUMMARIZE_SYSTEM = """Tu es un agent de synthèse web.
Tu reçois des extraits de pages web sur un sujet.
Synthétise les informations clés en 3-5 points factuels.
Identifie les faits les plus importants à mémoriser.

Réponds en JSON :
{
  "summary": "synthèse en 2-3 phrases",
  "key_facts": ["fait 1", "fait 2", "fait 3"],
  "sources": ["url1", "url2"]
}"""

MAX_RESULTS   = 5
SNIPPET_LIMIT = 300   # chars par snippet


class WebSearchAgent:
    def __init__(self, llm: LLMClient, store: Optional[MemoryStore] = None):
        self.llm   = llm
        self.store = store
        try:
            try:
                from ddgs import DDGS          # package renommé (>=7.x)
            except ImportError:
                from duckduckgo_search import DDGS  # ancien nom (fallback)
            self._ddgs = DDGS()
            self._available = True
            logger.info("[WebSearch] DuckDuckGo initialisé")
        except ImportError:
            self._available = False
            logger.warning("[WebSearch] ddgs non installé — pip install ddgs")

    def search(self, query: str, max_results: int = MAX_RESULTS,
               save_to_memory: bool = True) -> dict:
        """
        Recherche web + synthèse LLM + (optionnel) sauvegarde MEA.
        Retourne { summary, key_facts, sources, raw_results }.
        """
        if not self._available:
            return {
                "summary":     "[WebSearch non disponible — pip install duckduckgo-search]",
                "key_facts":   [],
                "sources":     [],
                "raw_results": [],
            }

        logger.info(f"[WebSearch] requête : {query[:80]}")
        raw = self._ddgs_search(query, max_results)

        if not raw:
            return {"summary": "Aucun résultat trouvé.", "key_facts": [], "sources": [], "raw_results": []}

        # Prépare le contexte pour le LLM
        context_lines = []
        for r in raw:
            title   = r.get("title", "")[:80]
            snippet = r.get("body", r.get("snippet", ""))[:SNIPPET_LIMIT]
            url     = r.get("href", r.get("url", ""))
            context_lines.append(f"[{title}]\n{snippet}\n{url}")

        context = "\n\n---\n\n".join(context_lines)
        user_prompt = f"Sujet : {query}\n\nExtraits web :\n{context}"

        # Synthèse via LLM local (tâche "search" → Ollama si dispo)
        raw_response = self.llm.call(SUMMARIZE_SYSTEM, user_prompt, task="search")
        result = self._parse_response(raw_response, raw)

        # Sauvegarde dans la MEA
        if save_to_memory and self.store and result.get("key_facts"):
            self._save_facts(query, result)

        logger.info(f"[WebSearch] {len(result.get('key_facts', []))} faits extraits — {len(raw)} sources")
        return result

    def _ddgs_search(self, query: str, max_results: int) -> List[dict]:
        try:
            results = list(self._ddgs.text(query, max_results=max_results))
            return results
        except Exception as e:
            logger.warning(f"[WebSearch] DDG error: {e}")
            return []

    def _parse_response(self, raw: str, ddg_results: list) -> dict:
        import re
        raw = raw.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if match:
            raw = match.group(1).strip()
        try:
            data = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
            # Complète les sources avec les URLs DDG si manquantes
            if not data.get("sources"):
                data["sources"] = [r.get("href", r.get("url", "")) for r in ddg_results[:3]]
            data["raw_results"] = ddg_results
            return data
        except Exception:
            # Fallback si le JSON est malformé
            return {
                "summary":     raw[:400],
                "key_facts":   [raw[:200]],
                "sources":     [r.get("href", "") for r in ddg_results[:3]],
                "raw_results": ddg_results,
            }

    def _save_facts(self, query: str, result: dict) -> None:
        """Persiste les faits clés dans la MEA."""
        import uuid
        from datetime import datetime
        for fact in result.get("key_facts", [])[:3]:
            if len(fact.strip()) < 10:
                continue
            entry = MemoryEntry(
                id         = str(uuid.uuid4())[:8],
                type       = "fact",
                scope      = "web",
                context    = {"query": query, "sources": result.get("sources", [])[:2]},
                summary    = fact[:120],
                details    = result.get("summary", ""),
                links      = result.get("sources", [])[:3],
                importance = "medium",
                created_at = datetime.utcnow().isoformat(),
            )
            self.store.save_entry(entry)
        logger.debug(f"[WebSearch] {len(result.get('key_facts', []))} faits sauvegardés en MEA")
