"""
generate_daily.py — Générateur de compte-rendu quotidien
=========================================================
Génère le fichier journal/YYYY-MM-DD.md à la fin de chaque journée.
Peut être appelé manuellement ou automatiquement par run_continuous.py.

Usage :
  python journal/generate_daily.py
  python journal/generate_daily.py --date 2026-04-27
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

import yaml
from askio1.tools.llm_client import LLMClient
from askio1.memory.store import MemoryStore

JOURNAL_DIR = Path(__file__).parent
PROGRESS_FILE = Path("data/progress.json")
HEARTBEAT_FILE = Path("data/heartbeat.json")

REPORT_SYSTEM = """Tu es le secrétaire de bord d'un projet robotique autonome.
Tu génères un compte-rendu quotidien clair, structuré, et lisible pour une vidéo YouTube.

Le ton est : direct, technique mais accessible, enthousiaste sans être creux.
Parle à la première personne du pluriel ("on a", "on a fait", "prochaine étape").
Pas de bullet points excessifs — des phrases courtes et percutantes.

Structure OBLIGATOIRE (markdown) :
# Compte-rendu — {date}

## Ce qu'on a fait aujourd'hui
(3-5 points concrets, avec détails techniques si pertinent)

## Décisions importantes
(1-3 décisions prises, avec le raisonnement court)

## Artifacts produits
(liste des fichiers/code générés, avec leur rôle)

## Métriques du jour
(cycles cognitifs, appels API, entrées MEA, artifacts)

## Prochaines étapes
(top 3 priorités pour demain — actionnable)

---
*Généré par Askio1 v2 le {datetime}*
"""


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def load_heartbeat() -> dict:
    if HEARTBEAT_FILE.exists():
        try:
            return json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def get_today_log() -> list:
    """Charge le log de session le plus récent."""
    log_dir = Path("data/logs")
    if not log_dir.exists():
        return []
    today = date.today().strftime("%Y%m%d")
    logs = sorted(log_dir.glob(f"continuous_{today}*.log"), reverse=True)
    if not logs:
        # Prend le plus récent peu importe la date
        logs = sorted(log_dir.glob("continuous_*.log"), reverse=True)
    if not logs:
        return []
    lines = logs[0].read_text(encoding="utf-8").splitlines()
    return [l for l in lines if any(k in l for k in ["TÂCHE", "verdict", "arrêt", "ASKIO", "CODE_TASK"])]


def get_artifacts_today() -> list:
    """Liste les artifacts créés aujourd'hui."""
    artifacts_dir = Path("data/artifacts")
    if not artifacts_dir.exists():
        return []
    today = date.today().strftime("%Y%m%d")
    found = []
    for artifact_type in artifacts_dir.iterdir():
        if not artifact_type.is_dir():
            continue
        for artifact in artifact_type.iterdir():
            if artifact.is_dir() and artifact.name.startswith(today):
                readme = artifact / "README.md"
                desc = artifact.name
                if readme.exists():
                    lines = readme.read_text().splitlines()
                    desc = next((l.replace("# Artifact : ", "") for l in lines if l.startswith("# Artifact")), desc)
                found.append(f"[{artifact_type.name}] {desc[:80]}")
    return found


def generate_report(target_date: str = None) -> str:
    """Génère le compte-rendu via LLM."""
    config = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    llm    = LLMClient(config)
    store  = MemoryStore(config)

    if not target_date:
        target_date = date.today().isoformat()

    # Collecte des données
    progress  = load_progress()
    heartbeat = load_heartbeat()
    log_lines = get_today_log()
    artifacts = get_artifacts_today()
    mea_stats = store.stats()

    # Mémoire récente
    recent_memory = store.retrieve_relevant(
        "robot locomotion firmware simulation prototype", max_results=5
    )

    context = f"""Date : {target_date}

=== PROGRESSION ===
Cycles complétés : {progress.get('cycle', 'N/A')}
Session ID : {progress.get('session_id', 'N/A')}
MEA stats : {mea_stats}

=== HEARTBEAT ===
Ollama up : {heartbeat.get('ollama_up', False)}
Uptime % : {heartbeat.get('uptime_pct', 0)}%

=== LOGS DU JOUR (extraits) ===
{chr(10).join(log_lines[-20:]) if log_lines else 'Aucun log trouvé pour aujourd\'hui.'}

=== ARTIFACTS PRODUITS ===
{chr(10).join(artifacts) if artifacts else 'Aucun artifact produit aujourd\'hui.'}

=== MÉMOIRE RÉCENTE (MEA) ===
{recent_memory[:1000] if recent_memory else 'MEA vide ou non disponible.'}
"""

    system = REPORT_SYSTEM.format(
        date=target_date,
        datetime=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    report = llm.call(system, context, task="reflect")
    return report


def save_report(report: str, target_date: str = None) -> Path:
    if not target_date:
        target_date = date.today().isoformat()
    output_path = JOURNAL_DIR / f"{target_date}.md"
    output_path.write_text(report, encoding="utf-8")
    print(f"✅ Compte-rendu sauvegardé : {output_path}")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Génère le compte-rendu quotidien")
    parser.add_argument("--date", default=None, help="Date cible (YYYY-MM-DD)")
    args = parser.parse_args()

    print(f"📝 Génération du compte-rendu pour {args.date or date.today().isoformat()}...")
    report = generate_report(args.date)
    path   = save_report(report, args.date)
    print(f"\n--- APERÇU ---\n{report[:500]}...")
