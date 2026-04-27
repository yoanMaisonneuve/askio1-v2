# Askio1 v2 — Système cognitif augmenté

Architecture multi-agent avec Mémoire Externe Auto-construite (MEA).

## Architecture

5 agents cognitifs :
- **Observer** — lit, collecte, extrait, surveille
- **Penseur (Thinker)** — raisonne, structure, planifie
- **Exécuteur (Executor)** — agit, code, appelle des outils
- **Réviseur (Reviewer)** — évalue, critique, corrige, stabilise
- **MemoryAgent (Mémoire)** — stocke, indexe, résume, élève

## Plan d'implantation

| Phase | Durée | Objectif |
|-------|-------|----------|
| Phase 0 | 1–2 jours | Préparation — arborescence, dépendances, MISSION_CARD |
| Phase 1 | 3–5 jours | Agents — implémentation des rôles cognitifs |
| Phase 2 | 3–7 jours | Mémoire vivante — JSON, indexation, retrieval, reflection |
| Phase 3 | 5–10 jours | Boucle cognitive — boucle courte + longue + triggers |
| Phase 4 | 7–14 jours | Robot learning — contrôleur, perturbation, exécution |
| Phase 5 | 7–14 jours | Cognition fractale — niveaux micro/méso/macro |
| Phase 6 | 14–30 jours | Askio1 v2 — intégration, stabilisation, transmission |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Ajouter ANTHROPIC_API_KEY dans .env
python -m askio1.orchestrator.main
```
