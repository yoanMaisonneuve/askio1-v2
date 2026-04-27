# VISION — Askio1 v2 × Robot 3D Imprimable
*Dernière mise à jour : 2026-04-27*

---

## Principe directeur

> L'orchestrateur local n'a pas besoin d'être intelligent.  
> Il doit juste savoir **quoi déléguer à qui**.

Le laptop planifie. Claude Code code. Les modèles forts raisonnent.  
Le robot apprend dans la simulation avant de toucher le monde réel.

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
│   └── Délégation code → Claude Code (CLI subprocess)       │
└──────────────────────────┬──────────────────────────────────┘
                           │ délègue
┌──────────────────────────▼──────────────────────────────────┐
│  COUCHE 2 — EXÉCUTANTS SPÉCIALISÉS                          │
│                                                             │
│  Claude Code (claude --code)                                │
│   ├── Génération firmware robot (MicroPython, C++ Arduino) │
│   ├── Contrôleurs de locomotion (Python, ROS2)             │
│   ├── Scripts simulation Gazebo / Isaac Sim                │
│   └── Tests unitaires + validation                         │
│                                                             │
│  Claude API (Opus)                                          │
│   ├── Conception architecture mécanique                    │
│   ├── Raisonnement sur les compromis techniques            │
│   └── Revue critique des résultats simulation              │
└──────────────────────────┬──────────────────────────────────┘
                           │ teste
┌──────────────────────────▼──────────────────────────────────┐
│  COUCHE 3 — ENVIRONNEMENTS DE TEST                          │
│                                                             │
│  Gazebo (ROS2)          ← commence ici (CPU, accessible)   │
│  Isaac Sim (NVIDIA)     ← quand la tour GPU est prête       │
│  Monde réel             ← après validation simulation       │
└─────────────────────────────────────────────────────────────┘
```

---

## Infrastructure — évolution

| Phase | Setup | Usage |
|-------|-------|-------|
| **Maintenant** | Laptop + API Anthropic | Orchestration, planification, MEA |
| **Court terme** | + Ollama local (Qwen 2.5 7B) | Tâches légères, consolidation, search |
| **Tour GPU** | RTX 4090 ou H100 PCIe | Modèles 70B+, entraînement RL, Isaac Sim |
| **Si scale** | RunPod H100 SXM (~2.50$/h) | Bursts d'entraînement, pas de commit long terme |

**Tour GPU — recommandations :**
- GPU : RTX 4090 (24 GB VRAM) → modèles jusqu'à 70B quantizés, Isaac Sim
- RAM : 64 GB minimum (simulation + modèle simultanés)
- Stockage : NVMe 2 TB (checkpoints, datasets simulation)
- OS : Ubuntu 22.04 (ROS2 Humble natif)

---

## Roadmap robot — 5 phases

### Phase R1 : Conception mécanique (6-8 semaines)
**Objectif** : un design 3D imprimable validé sur papier

- Choix de morphologie : **quadrupède** (recommandé — stabilité passive, plus facile que bipède)
  - Alternative : wheeled bot pour commencer, legs après
- Contraintes : PLA/PETG, servos standard (MG996R ou STS3215), < 1.5 kg total
- DOF cible : 12 DOF (3 par patte) pour quadrupède, ou 6 DOF pour bras robot
- Outil : FreeCAD (paramétrique, open source) ou OpenSCAD
- Livrable : fichiers STL + BOM (Bill of Materials)

**Tâches askio1 :**
```
[ ] Rechercher designs open-source existants (OpenDog, SpotMicro, Petoi)
[ ] Analyser compromis morphologie (bipède vs quadrupède vs hexapode)
[ ] Générer spécifications mécaniques complètes
[ ] Claude Code → script FreeCAD paramétrique
```

### Phase R2 : Stack électronique + firmware (4-6 semaines)
**Objectif** : microcontrôleur qui pilote les servos

- MCU : **Raspberry Pi 5** (4 GB) + coprocesseur RP2040 pour temps réel
  - Alternative légère : ESP32-S3 si budget serré
- IMU : ICM-42688-P (6-axis, haute précision)
- Communication : USB-C + WiFi pour debugging, BLE pour téléopération
- Batterie : LiPo 3S 2200 mAh, BMS intégré
- Livrable : schéma électrique + firmware de base (contrôle servo, lecture IMU)

**Tâches Claude Code :**
```
[ ] Firmware servo controller (MicroPython ou C++ selon MCU choisi)
[ ] Driver IMU + kalman filter pour orientation
[ ] Interface ROS2 ↔ firmware (rosserial ou micro-ROS)
```

### Phase R3 : Simulation Gazebo (8-10 semaines)
**Objectif** : robot qui marche dans Gazebo, ROS2 Humble

- URDF/Xacro du robot généré depuis le design CAD
- Plugin Gazebo pour les servos et l'IMU
- Contrôleur de base : CPG (Central Pattern Generator) pour gait
- Métriques : distance parcourue, stabilité, consommation énergétique simulée
- Livrable : robot qui marche en ligne droite de façon stable

**Tâches Claude Code :**
```
[ ] Générateur URDF depuis spécifications mécaniques
[ ] World Gazebo + launch files ROS2
[ ] CPG controller Python (ros2_control)
[ ] Scripts de métriques et visualisation
```

### Phase R4 : Isaac Sim + apprentissage (quand tour GPU prête)
**Objectif** : politique de locomotion par RL, meilleure que CPG

- Isaac Sim : physique GPU-accélérée, 1000+ instances parallèles
- Framework RL : Isaac Lab (successeur d'OmniIsaacGymEnvs)
- Algo : PPO ou SAC, reward = vitesse forward + stabilité - énergie
- Transfer learning : sim-to-real avec domain randomization
- Livrable : politique RL exportée (ONNX) qui surpasse CPG

### Phase R5 : Prototype réel
**Objectif** : le robot imprimé marche dans le monde réel

- Impression : 40-60h total PLA, remplissage 30%, 0.2mm
- Assemblage : 2-3 jours
- Flashing firmware + déploiement politique ONNX sur RPi5
- Tests : sol dur, légère pente, obstacles simples
- Livrable : vidéo du robot qui marche

---

## Intégration Claude Code dans askio1

```python
# À ajouter dans askio1/agents/executor.py (Phase 8)
# Quand le plan contient une tâche de code substantielle,
# déléguer à Claude Code via subprocess

import subprocess

def delegate_to_claude_code(task_description: str, workspace: str) -> str:
    """Lance Claude Code en mode non-interactif sur une tâche de code."""
    result = subprocess.run(
        ["claude", "--print", task_description],
        capture_output=True, text=True,
        cwd=workspace, timeout=300
    )
    return result.stdout.strip()
```

Routing : si le plan contient `CODE_TASK:`, l'Executor délègue à Claude Code.  
Le résultat revient dans la MEA comme entrée de type `code_artifact`.

---

## Prochaines actions immédiates

1. **Installer Ollama** sur le laptop → `ollama pull qwen2.5:7b`
2. **Lancer `run_continuous.py`** — il va consommer les tâches robot dans `tasks.json`
3. **Phase 8** — intégration Claude Code dans l'Executor (délégation CODE_TASK)
4. **Choisir la morphologie robot** — décision bloquante pour toute la suite
5. **Commander les composants** — servos, MCU, IMU, batterie (estimé 150-300 CAD)

---

## Décisions ouvertes

| Question | Options | Décision |
|----------|---------|----------|
| Morphologie robot | Quadrupède / Bipède / Wheeled | **À décider** |
| MCU principal | RPi 5 / ESP32-S3 / STM32 | **RPi 5 recommandé** |
| Simulation départ | Gazebo / Isaac Sim | **Gazebo d'abord** |
| GPU tour | RTX 4090 / H100 PCIe | **RTX 4090 recommandé** |
| Modèle local 70B | Llama 3.3 70B / Qwen 2.5 72B | **Qwen 2.5 72B recommandé** |

---

*Ce document est vivant — askio1 le met à jour via la MEA à chaque cycle pertinent.*
