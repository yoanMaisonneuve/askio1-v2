# Plan de communication — Askio1 v2 × Robot

## Canal principal : Dispatch (Cowork Claude)
Communication temps réel entre Yoan et Askio1.  
Yoan donne la direction. Askio1 exécute et rend compte.  
Messages courts, actionnables, sans remplissage.

## Suivi de projet : GitHub (ce repo)

### Fichiers de référence
| Fichier | Rôle |
|---------|------|
| `VISION.md` | Architecture, roadmap, décisions — source de vérité |
| `COMMUNICATION.md` | Ce fichier — plan de com |
| `tasks.json` | Queue de tâches actives (modifiable en direct) |
| `journal/YYYY-MM-DD.md` | Compte-rendu quotidien auto-généré |
| `data/progress.json` | État de session courant (cycle, stats) |

### Quand le projet grandit
- **Issues GitHub** : décisions bloquantes, questions ouvertes, bugs
- **Milestones GitHub** : PROTO-1 Gazebo / PROTO-2 Hardware / PROTO-4 Roues
- **Tags git** : `proto1-sim-ok`, `proto2-hardware-v1`, etc.

## Compte-rendu quotidien → vidéo
- Généré automatiquement à la fin de chaque session `run_continuous.py`
- Fichier : `journal/YYYY-MM-DD.md`
- Format : Ce qu'on a fait · Décisions · Artifacts · Suite

## Escalade
Si Askio1 bloque sur une décision de direction → entrée MEA `decision_needed`  
Yoan la voit dans le compte-rendu du lendemain ou dans Dispatch.

## Règles de collaboration
- Yoan = visionnaire/consultant → donne la direction, valide les virages majeurs
- Askio1 = CEO autonome → exécute, décide les détails, rend compte
- Tout ce qui est technique → Askio1 décide seul
- Tout ce qui change la direction du projet → Askio1 demande
