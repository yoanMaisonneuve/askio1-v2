# VISION — Askio1 v2 × Robot
*Dernière mise à jour : 2026-04-27*
*Direction : Yoan Maisonneuve (visionnaire) · Exécution : Askio1 (CEO autonome)*

---

## Principe directeur

> L'orchestrateur local n'a pas besoin d'être intelligent.  
> Il doit juste savoir **quoi déléguer à qui**.

Le laptop planifie. Claude Code code. Les modèles forts raisonnent.  
Le robot apprend dans la simulation avant de toucher le monde réel.  
Les morphologies évoluent en parallèle — on itère, on ne choisit pas une seule voie.

---

## Architecture système — 3 couches

```
┌─────────────────────────────────────────────────────────────┐
│  COUCHE 1 — ORCHESTRATEUR LOCAL (laptop / tour GPU)         │
│                                                             │
│  askio1_v2 (run_continuous.py)                              │
│   ├── Planificateur : Opus via API (plan/reflect/judge)     │
│   ├── Exécution légère : Qwen 2.5 7B via Ollama             │
│   ├── Recherche web : WebSearchAgent (DuckDuckGo)           │
│   ├── Mémoire : MEA (TF-IDF, decay, consolidation)         │
│   └── Délégation code → ClaudeCodeAgent (Phase 8)          │
└──────────────────────────┬──────────────────────────────────┘
                           │ délègue selon type
              ┌────────────┴──────────────┐
              ▼                           ▼
┌─────────────────────┐    ┌──────────────────────────────────┐
│  Claude Code CLI    │    │  Claude API (Opus)               │
│  CODE_TASK → code  │    │  Raisonnement, architecture,     │
│  réel livré        │    │  critique, décisions bloquantes  │
└─────────────────────┘    └──────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│  COUCHE 3 — ENVIRONNEMENTS DE TEST                          │
│                                                             │
│  Gazebo (ROS2)     ← commence ici (CPU, accessible)        │
│  Isaac Sim         ← quand la tour GPU est prête            │
│  Monde réel        ← après validation simulation            │
└─────────────────────────────────────────────────────────────┘
```

---

## Roadmap morphologie robot — itération parallèle

> Pas une seule voie. Plusieurs prototypes en simulation en parallèle.  
> Le hardware suit le meilleur candidat simulation.

```
PROTO-1 : Tripode (3 pattes)
  ├── Stabilité passive garantie (triangle)
  ├── 9 DOF (3 par patte)
  ├── Idéal pour valider : firmware, IMU, boucle sim→réel
  └── Timeline : premier dans Gazebo

PROTO-2 : Quadrupède (4 pattes)
  ├── Inspiré SpotMicro (designs open-source abondants)
  ├── 12 DOF, gait naturel
  ├── Développé en parallèle dans Gazebo
  └── Candidat principal pour premier hardware

PROTO-3 : Appendice / Queue
  ├── 5e membre : support d'appui OU outil (pince, capteur)
  ├── S'ajoute sur PROTO-2 ou PROTO-1
  ├── Ouvre la voie à la manipulation
  └── Testé en simulation avant intégration hardware

PROTO-4 : Bipède sur roues
  ├── 2 pattes avec roues à la base
  ├── Peut rouler (rapide) ou marcher (terrain difficile)
  ├── Objectif long terme — nécessite RL avancé
  └── Commence en simulation dès que PROTO-2 est stable
```

**Décision d'exécution** : PROTO-1 et PROTO-2 en simulation simultanément.  
PROTO-3 et PROTO-4 démarrent en simulation dès que PROTO-2 marche.  
Hardware = meilleur candidat sim après validation 2 semaines.

---

## Infrastructure — évolution

| Phase | Setup | Modèles locaux |
|-------|-------|----------------|
| **Maintenant** | Laptop + Ollama (Qwen 2.5 7B) | 7B — tâches légères |
| **Tour GPU** | RTX 4090 (24 GB) | Qwen 2.5 72B Q4, Isaac Sim |
| **Si burst** | RunPod H100 SXM (~2.50$/h) | Entraînement RL, pas de commit |

**Tour GPU** : RTX 4090 recommandé (24 GB VRAM, ~1800 CAD).  
Qwen 2.5 72B Q4_K_M tourne en ~20 GB. Isaac Sim parallèle possible.  
Pas urgent — on continue avec API Anthropic en attendant.

---

## Roadmap logicielle — phases

### ✅ Phase 1-6 : Fondations (terminé)
MEA, boucle cognitive, TF-IDF, cross-session, évaluation, API FastAPI.

### ✅ Phase 7 : Autonomie continue (terminé)
Heartbeat Ollama, WebSearchAgent, run_continuous.py, tasks.json.

### 🔄 Phase 8 : Claude Code dans la boucle (en cours)
Executor détecte `CODE_TASK:` → délègue à ClaudeCodeAgent → livraison réelle.  
Artifacts sauvegardés dans `data/artifacts/` + MEA.

### Phase 9 : Stack simulation Gazebo
URDF/Xacro générateur automatique depuis spécifications MEA.  
Launch files ROS2. CPG controller. Métriques automatiques.

### Phase 10 : Boucle sim→design
Quand simulation échoue → entrée MEA `sim_failure` avec contexte.  
Le planificateur utilise ces entrées pour corriger le design.  
Ferme la boucle : MEA ↔ CAD ↔ Simulation ↔ MEA.

### Phase 11 : Isaac Sim + RL (tour GPU)
Isaac Lab, PPO/SAC, 1000 instances parallèles.  
Export politique ONNX → déploiement firmware RPi5.

### Phase 12 : Hardware PROTO-1 / PROTO-2
Impression, assemblage, tests réels.

---

## Gestion des artifacts

```
data/
├── artifacts/
│   ├── cad/          ← fichiers FreeCAD, STL, STEP
│   ├── firmware/     ← code C++, MicroPython, ROS2 packages
│   ├── simulation/   ← URDF, worlds Gazebo, launch files
│   ├── policies/     ← modèles RL entraînés (.onnx, .pt)
│   └── reports/      ← rapports de simulation, métriques
├── memory/           ← MEA
└── logs/             ← logs continus
```

Chaque artifact : `{date}_{type}_{description}/` avec `README.md` auto-généré.  
Index dans MEA comme entrée de type `code_artifact`.  
Référencé dans session_resume.json pour cold start.

---

## Boucle feedback sim→design

```
Simulation échoue (robot tombe, instabilité, collision)
         ↓
Reviewer extrait métriques d'échec
         ↓
MEA ← entrée sim_failure {proto, cause, métriques}
         ↓
Planificateur (Opus) lit sim_failure + design actuel
         ↓
Génère correction : ajuster DOF / masse / longueur membre
         ↓
CODE_TASK → Claude Code régénère URDF + STL paramétrique
         ↓
Relance simulation → métriques → MEA
         ↓
(boucle jusqu'à stabilité)
```

---

## Budget estimé

| Poste | Estimation |
|-------|-----------|
| Servos × 12 (MG996R ou STS3215) | 80-150 CAD |
| MCU (RPi 5 4GB) | 80 CAD |
| IMU (ICM-42688) + divers | 30 CAD |
| Batterie LiPo 3S + BMS + chargeur | 60 CAD |
| Filament PLA (2 kg) | 40 CAD |
| Quincaillerie (vis, inserts) | 20 CAD |
| **Total hardware proto** | **~330 CAD** |
| API Anthropic (Opus, phases 8-12) | ~50-100 CAD/mois |
| RunPod bursts (entraînement RL) | ~20-50 CAD/session |

---

## Décisions actives

| Question | Décision |
|----------|----------|
| Morphologie départ | PROTO-1 (tripode) + PROTO-2 (quad) en parallèle simulation |
| Morphologie cible | PROTO-4 (bipède roues) — long terme |
| Appendice/queue | PROTO-3 ajouté sur PROTO-2 après validation |
| MCU | Raspberry Pi 5 (4 GB) + RP2040 temps réel |
| Simulation départ | Gazebo (ROS2 Humble) |
| GPU | RTX 4090 — pas urgent, en tête |
| Organisation | Yoan = visionnaire/consultant · Askio1 = CEO autonome |

---

*Ce document est vivant — askio1 le met à jour à chaque décision majeure.*
