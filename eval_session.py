"""
eval_session.py — Phase 5 : Évaluation Comparative Askio1 v2
=============================================================
Compare 3 conditions sur un ensemble fixe de questions :

  CONDITION A — Baseline (pas de MEA, pas de cold start)
  CONDITION B — MEA active (retrieve_relevant branché)
  CONDITION C — MEA + cold start (contexte cross-session injecté)

Scoring LLM-as-judge sur 4 dimensions [0-10] :
  • pertinence   — la réponse répond-elle à la question ?
  • profondeur   — la réponse est-elle détaillée et structurée ?
  • cohérence    — cohérence interne + avec les échanges précédents ?
  • exploitabilité — peut-on s'en servir directement ?

Sortie :
  data/eval/eval_<timestamp>.json — résultats bruts
  data/eval/eval_<timestamp>.md   — rapport Markdown lisible
"""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import mean

import yaml
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from askio1.agents.observer import Observer
from askio1.agents.thinker import Thinker
from askio1.agents.executor import Executor
from askio1.agents.reviewer import Reviewer
from askio1.agents.memory_agent import MemoryAgent
from askio1.memory.store import MemoryStore
from askio1.tools.llm_client import LLMClient
from askio1.cognitive_loop import CognitiveLoop

# ─── Logging fichier uniquement ───────────────────────────────────────────────
Path("data/eval").mkdir(parents=True, exist_ok=True)
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    handlers=[logging.FileHandler(f"data/eval/eval_{TS}.log", encoding="utf-8")],
)
logger = logging.getLogger("askio1.eval")

# ─── Questions d'évaluation (fixes — identiques pour les 3 conditions) ────────
EVAL_QUESTIONS = [
    "Qu'est-ce qu'une mémoire externe auto-construite et pourquoi est-elle utile ?",
    "Quels sont les 3 principes fondamentaux d'un système cognitif robuste ?",
    "Comment implémenter un mécanisme de decay exponentiel pour oublier progressivement des souvenirs anciens ?",
    "Quelle architecture recommanderais-tu pour un agent qui apprend de ses erreurs ?",
    "Comment décider quelle information mémoriser en priorité dans un système à mémoire limitée ?",
]

# ─── Prompt LLM-as-judge ──────────────────────────────────────────────────────
JUDGE_SYSTEM = """Tu es un évaluateur expert en systèmes cognitifs et IA.
Tu reçois une question et une réponse générée par un système multi-agents.
Évalue la réponse sur 4 critères, chacun entre 0 et 10.

IMPORTANT : Réponds UNIQUEMENT en JSON brut, sans bloc markdown.
Format exact :
{
  "pertinence": <0-10>,
  "profondeur": <0-10>,
  "coherence": <0-10>,
  "exploitabilite": <0-10>,
  "justification": "<1-2 phrases>"
}

Définitions :
- pertinence (0-10)    : la réponse répond-elle directement à la question ?
- profondeur (0-10)    : niveau de détail, structure, richesse de l'information
- coherence (0-10)     : cohérence interne, absence de contradictions
- exploitabilite (0-10): peut-on utiliser cette réponse directement (code, décision, action) ?"""


def load_config(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _clean_json(raw: str) -> str:
    import re
    raw = raw.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if match:
        return match.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    return raw[start:end+1] if start != -1 and end > start else raw


def judge_response(llm: LLMClient, question: str, response: str) -> dict:
    """LLM-as-judge : score la réponse sur 4 dimensions."""
    prompt = f"Question : {question}\n\nRéponse :\n{response[:3000]}"
    raw    = llm.call(JUDGE_SYSTEM, prompt)
    try:
        scores = json.loads(_clean_json(raw))
        return {
            "pertinence":    float(scores.get("pertinence",    0)),
            "profondeur":    float(scores.get("profondeur",    0)),
            "coherence":     float(scores.get("coherence",     0)),
            "exploitabilite":float(scores.get("exploitabilite",0)),
            "justification": scores.get("justification", ""),
        }
    except Exception as e:
        logger.warning(f"[Judge] parse error: {e} — raw={raw[:100]}")
        return {"pertinence": 0, "profondeur": 0, "coherence": 0, "exploitabilite": 0, "justification": f"parse_error: {e}"}


def run_condition(label: str, questions: list, llm: LLMClient, store: MemoryStore,
                  use_mea: bool, use_cold_start: bool) -> list:
    """
    Exécute les questions sous une condition donnée.
    Retourne une liste de résultats par question.
    """
    observer = Observer(llm, store)
    thinker  = Thinker(llm)
    executor = Executor(llm)
    reviewer = Reviewer(llm)
    cloop    = CognitiveLoop(store, llm)

    cold_ctx = cloop.cold_start() if use_cold_start else ""

    results = []
    print(f"\n  ▶ Condition {label} ({'MEA' if use_mea else 'sans MEA'}"
          f"{' + cold start' if use_cold_start else ''}) — {len(questions)} questions")

    for i, question in enumerate(questions, 1):
        sys.stdout.write(f"\r    Question {i}/{len(questions)}...")
        sys.stdout.flush()
        t0 = time.time()

        try:
            # Observer (toujours actif pour ne pas avantager A)
            obs = observer.observe(raw_text=question, context={"cycle": i, "condition": label})

            # Contexte MEA (conditionnel)
            if use_mea:
                snippets = store.retrieve_relevant(question)
                adaptive = cloop.cycle_start(i, question)
                enriched = f"{adaptive}\n\n[MEA]\n{snippets}" if adaptive else snippets
            else:
                enriched = "(aucune mémoire — condition baseline)"

            # Pipeline cognitif
            plan   = thinker.plan({"mission_id": "eval"}, question, enriched)
            result = executor.execute(plan=plan, context={"cycle": i})
            review = reviewer.review(result=result, goal=question, context={"cycle": i})
            verdict= review.get("verdict", "?") if isinstance(review, dict) else "?"

            if use_mea:
                mem_agent = MemoryAgent(llm, store)
                mem_agent.build_entries(observer_output=obs, context={"cycle": i})
                cloop.cycle_end(i, verdict, review.get("issues", []),
                                len(obs.get("candidates_for_memory", [])))

        except Exception as e:
            logger.error(f"[Eval {label}] Q{i} erreur: {e}")
            result  = f"[ERREUR: {e}]"
            verdict = "failure"

        elapsed = time.time() - t0
        results.append({
            "question":  question,
            "condition": label,
            "response":  result,
            "verdict":   verdict,
            "elapsed":   round(elapsed, 1),
        })
        logger.info(f"[Eval {label}] Q{i} verdict={verdict} elapsed={elapsed:.1f}s")

    print(f"\r    ✓ {len(results)} questions traitées                ")
    return results


def score_results(llm: LLMClient, results: list) -> list:
    """Ajoute les scores LLM-as-judge à chaque résultat."""
    print(f"  ⚖  Scoring LLM-as-judge ({len(results)} réponses)...")
    for i, r in enumerate(results, 1):
        sys.stdout.write(f"\r    Score {i}/{len(results)}...")
        sys.stdout.flush()
        scores = judge_response(llm, r["question"], r["response"])
        r["scores"] = scores
        r["global_score"] = round(mean([
            scores["pertinence"], scores["profondeur"],
            scores["coherence"],  scores["exploitabilite"]
        ]), 2)
    print(f"\r    ✓ Scoring terminé                ")
    return results


def generate_report(all_results: dict, output_path: Path) -> str:
    """Génère un rapport Markdown comparatif."""
    dims = ["pertinence", "profondeur", "coherence", "exploitabilite"]

    lines = [
        "# Askio1 v2 — Rapport d'Évaluation Phase 5",
        f"\n_Généré le {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n",
        "## 1. Scores Globaux par Condition\n",
        "| Condition | Pertinence | Profondeur | Cohérence | Exploitabilité | **Global** | Verdicts ✓ |",
        "|-----------|-----------|-----------|----------|--------------|-----------|-----------|",
    ]

    condition_summaries = {}
    for label, results in all_results.items():
        dim_avgs = {d: round(mean(r["scores"][d] for r in results if "scores" in r), 2) for d in dims}
        global_avg = round(mean(r["global_score"] for r in results if "global_score" in r), 2)
        successes = sum(1 for r in results if r.get("verdict") == "success")
        condition_summaries[label] = {"dims": dim_avgs, "global": global_avg, "successes": successes}
        lines.append(
            f"| **{label}** | {dim_avgs['pertinence']} | {dim_avgs['profondeur']} | "
            f"{dim_avgs['coherence']} | {dim_avgs['exploitabilite']} | **{global_avg}** | {successes}/{len(results)} |"
        )

    # Amélioration relative A→B et A→C
    if "A-Baseline" in condition_summaries and "B-MEA" in condition_summaries:
        a = condition_summaries["A-Baseline"]["global"]
        b = condition_summaries["B-MEA"]["global"]
        c = condition_summaries.get("C-MEA+ColdStart", {}).get("global", a)
        delta_b = round((b - a) / max(a, 0.01) * 100, 1)
        delta_c = round((c - a) / max(a, 0.01) * 100, 1)
        lines += [
            "\n## 2. Amélioration Relative\n",
            f"- MEA vs Baseline : **{delta_b:+.1f}%**",
            f"- MEA + Cold Start vs Baseline : **{delta_c:+.1f}%**",
        ]

    # Tableau par question
    lines += ["\n## 3. Détail par Question\n"]
    questions = EVAL_QUESTIONS
    for i, q in enumerate(questions):
        lines.append(f"\n### Q{i+1}: {q[:80]}")
        lines.append("\n| Condition | Global | Pertinence | Profondeur | Justification |")
        lines.append("|-----------|--------|-----------|-----------|--------------|")
        for label, results in all_results.items():
            if i < len(results):
                r = results[i]
                s = r.get("scores", {})
                justif = s.get("justification", "")[:80]
                lines.append(
                    f"| {label} | **{r.get('global_score', '?')}** | "
                    f"{s.get('pertinence', '?')} | {s.get('profondeur', '?')} | {justif} |"
                )

    report = "\n".join(lines)
    output_path.write_text(report, encoding="utf-8")
    return report


def run_eval():
    config = load_config()
    llm    = LLMClient(config)

    print("\n╔════════════════════════════════════════════════╗")
    print("║  ASKIO1 v2 — Phase 5 : Évaluation Comparative  ║")
    print("╚════════════════════════════════════════════════╝\n")
    print(f"  {len(EVAL_QUESTIONS)} questions × 3 conditions + scoring LLM-as-judge")
    print(f"  Durée estimée : ~{len(EVAL_QUESTIONS) * 3 * 30 // 60} min\n")

    all_results = {}

    # ── Condition A : Baseline (store vide, pas de MEA) ───────────────────────
    store_a = MemoryStore({"memory": {"long_term_dir": "data/eval/store_a"}})
    raw_a   = run_condition("A-Baseline", EVAL_QUESTIONS, llm, store_a,
                            use_mea=False, use_cold_start=False)
    all_results["A-Baseline"] = score_results(llm, raw_a)

    # ── Condition B : MEA active (store réel, cold start désactivé) ───────────
    store_b = MemoryStore(config)
    raw_b   = run_condition("B-MEA", EVAL_QUESTIONS, llm, store_b,
                            use_mea=True, use_cold_start=False)
    all_results["B-MEA"] = score_results(llm, raw_b)

    # ── Condition C : MEA + cold start ───────────────────────────────────────
    store_c = MemoryStore(config)
    raw_c   = run_condition("C-MEA+ColdStart", EVAL_QUESTIONS, llm, store_c,
                            use_mea=True, use_cold_start=True)
    all_results["C-MEA+ColdStart"] = score_results(llm, raw_c)

    # ── Sauvegarde JSON ───────────────────────────────────────────────────────
    json_path = Path(f"data/eval/eval_{TS}.json")
    json_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Rapport Markdown ──────────────────────────────────────────────────────
    md_path = Path(f"data/eval/eval_{TS}.md")
    report  = generate_report(all_results, md_path)

    print("\n" + "=" * 55)
    print("ÉVALUATION TERMINÉE")
    print("=" * 55)

    # Résumé console
    for label, results in all_results.items():
        scored = [r for r in results if "global_score" in r]
        if scored:
            avg = round(mean(r["global_score"] for r in scored), 2)
            print(f"  {label:25s} → score global moyen : {avg}/10")

    print(f"\n  JSON  : {json_path}")
    print(f"  MD    : {md_path}\n")
    return str(json_path), str(md_path)


if __name__ == "__main__":
    run_eval()
