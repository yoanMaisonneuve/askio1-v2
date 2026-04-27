# Journal de bord — Robot × Askio1 v2

Ce dossier contient les comptes-rendus quotidiens du projet.  
Chaque fichier est généré automatiquement par Askio1 à la fin de la journée.

---

## Projet

**Nom** : Askio1 v2 × Robot  
**Objectif** : Construire un robot imprimable en 3D, testé en simulation (Gazebo → Isaac Sim), puis dans le monde réel.  
**Direction** : Yoan Maisonneuve  
**Exécution** : Askio1 (système cognitif autonome)

**Morphologies planifiées** :
- PROTO-1 : Tripode (3 pattes, 9 DOF) — stabilité parfaite, premier prototype
- PROTO-2 : Quadrupède (4 pattes, 12 DOF) — standard, bien documenté
- PROTO-3 : Appendice/queue (outil ou appui supplémentaire)
- PROTO-4 : Bipède sur roues — objectif long terme

**Stack technique** :
- Orchestration : Askio1 v2 (Python, MEA, boucle cognitive)
- Code : Claude Code CLI (délégation automatique)
- Simulation : Gazebo ROS2 → Isaac Sim (tour GPU)
- Firmware : MicroPython + ROS2 sur Raspberry Pi 5 + RP2040
- Hardware : servos MG996R ou STS3215, PLA/PETG, LiPo 3S

---

## Format des comptes-rendus

Chaque fichier suit le format `YYYY-MM-DD.md` et contient :

```
# Compte-rendu — YYYY-MM-DD

## Ce qui a été fait
- Tâches complétées, code produit, décisions prises

## Décisions importantes
- Choix techniques ou de direction

## Artifacts produits
- Liens vers les fichiers générés (firmware, URDF, etc.)

## Prochaines étapes
- Top 3 priorités pour demain

## Métriques
- Cycles cognitifs, appels API, entrées MEA
```

---

## Utilisation pour les vidéos quotidiennes

Le compte-rendu du jour est dans `journal/YYYY-MM-DD.md`.  
Il est conçu pour être lu tel quel ou résumé en voix off.  
Structure en 4 sections : fait · décisions · artifacts · suite.

---

*Généré automatiquement par Askio1 v2 — journal/generate_daily.py*
