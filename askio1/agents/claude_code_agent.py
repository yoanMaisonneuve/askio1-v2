"""
claude_code_agent.py — ClaudeCodeAgent (Phase 8)
=================================================
Délègue les tâches de code substantielles au CLI Claude Code.

Fonctionnement :
  1. Reçoit une description de tâche de code (CODE_TASK)
  2. Lance `claude --print "<prompt>"` en subprocess non-interactif
  3. Capture le code généré (fichiers, contenu)
  4. Sauvegarde l'artifact dans data/artifacts/{type}/
  5. Crée une entrée MEA de type "code_artifact"
  6. Retourne le résultat à l'Executor

Routing dans l'Executor :
  Si le plan contient "CODE_TASK:" → ClaudeCodeAgent.run()
  Sinon → Executor standard (LLM call)

Format CODE_TASK dans un plan :
  CODE_TASK: [firmware] Écrire le driver servo MG996R pour RP2040 en MicroPython
  CODE_TASK: [simulation] Générer le URDF pour PROTO-1 tripode 9-DOF
  CODE_TASK: [cad] Script FreeCAD paramétrique pour patte tripode

Artifact types : firmware | simulation | cad | policy | report | misc
"""

import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from askio1.memory.store import MemoryStore
from askio1.memory.schemas import MemoryEntry

logger = logging.getLogger(__name__)

# Répertoire racine des artifacts
ARTIFACTS_DIR = Path("data/artifacts")
ARTIFACT_TYPES = {"firmware", "simulation", "cad", "policy", "report", "misc"}

# Timeout pour Claude Code (secondes)
CLAUDE_CODE_TIMEOUT = 300

# Template de prompt enrichi pour Claude Code
CODE_PROMPT_TEMPLATE = """Tu es un expert en robotique et en code embarqué.
Contexte du projet : Robot imprimable en 3D, multi-morphologie (tripode → quadrupède → bipède roues).
Stack technique : ROS2, Gazebo, Python, MicroPython, C++, FreeCAD.

Tâche : {task}

Contexte MEA : {memory_context}

Instructions :
- Produis du code complet et fonctionnel, pas de pseudocode
- Inclus les imports, les types, la gestion d'erreurs
- Commente les parties non triviales
- Si plusieurs fichiers sont nécessaires, sépare-les clairement avec ## FILE: nom_fichier.py
"""


class ClaudeCodeAgent:
    """
    Agent qui délègue les tâches de code au CLI Claude Code.
    Fallback automatique vers LLM si Claude Code n'est pas installé.
    """

    def __init__(self, store: Optional[MemoryStore] = None):
        self.store = store
        self._available = self._check_claude_code()
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        for t in ARTIFACT_TYPES:
            (ARTIFACTS_DIR / t).mkdir(exist_ok=True)

        if self._available:
            logger.info("[ClaudeCode] CLI détecté — délégation active")
        else:
            logger.warning("[ClaudeCode] CLI non trouvé — fallback LLM activé")

    def _check_claude_code(self) -> bool:
        return shutil.which("claude") is not None

    def run(self, task: str, artifact_type: str = "misc",
            memory_context: str = "") -> dict:
        """
        Exécute une tâche de code.
        Retourne : {code, artifact_path, saved_to_mea, source}
        """
        logger.info(f"[ClaudeCode] tâche : {task[:80]}")

        if self._available:
            result = self._run_claude_code(task, memory_context)
        else:
            result = self._run_fallback(task, memory_context)

        # Sauvegarde l'artifact
        artifact_path = self._save_artifact(task, artifact_type, result["code"])
        result["artifact_path"] = str(artifact_path)

        # Sauvegarde dans la MEA
        if self.store and len(result["code"]) > 50:
            self._save_to_mea(task, artifact_type, artifact_path)
            result["saved_to_mea"] = True
        else:
            result["saved_to_mea"] = False

        logger.info(
            f"[ClaudeCode] artifact={artifact_path.name} "
            f"source={result['source']} len={len(result['code'])}"
        )
        return result

    def _run_claude_code(self, task: str, memory_context: str) -> dict:
        """Lance claude --print en subprocess."""
        prompt = CODE_PROMPT_TEMPLATE.format(
            task=task,
            memory_context=memory_context[:500] if memory_context else "Aucun contexte MEA disponible."
        )
        try:
            proc = subprocess.run(
                ["claude", "--print", prompt],
                capture_output=True,
                text=True,
                timeout=CLAUDE_CODE_TIMEOUT,
                env={**os.environ},
            )
            code = proc.stdout.strip()
            if not code:
                logger.warning("[ClaudeCode] sortie vide, fallback LLM")
                return self._run_fallback(task, memory_context)
            return {"code": code, "source": "claude_code", "error": None}
        except subprocess.TimeoutExpired:
            logger.error(f"[ClaudeCode] timeout après {CLAUDE_CODE_TIMEOUT}s")
            return self._run_fallback(task, memory_context)
        except Exception as e:
            logger.error(f"[ClaudeCode] erreur subprocess : {e}")
            return self._run_fallback(task, memory_context)

    def _run_fallback(self, task: str, memory_context: str) -> dict:
        """
        Fallback : génère le code via l'API Anthropic directement.
        Utilisé si Claude Code CLI n'est pas installé ou échoue.
        """
        try:
            import anthropic, os
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            prompt = CODE_PROMPT_TEMPLATE.format(
                task=task,
                memory_context=memory_context[:500] if memory_context else "Aucun contexte."
            )
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
            )
            return {"code": resp.content[0].text.strip(), "source": "anthropic_fallback", "error": None}
        except Exception as e:
            logger.error(f"[ClaudeCode] fallback API échoue : {e}")
            return {"code": f"# Erreur génération code : {e}", "source": "error", "error": str(e)}

    def _save_artifact(self, task: str, artifact_type: str, code: str) -> Path:
        """Sauvegarde le code dans data/artifacts/{type}/{date}_{slug}/"""
        if artifact_type not in ARTIFACT_TYPES:
            artifact_type = "misc"

        slug = re.sub(r"[^\w]", "_", task[:40]).lower().strip("_")
        date = datetime.now().strftime("%Y%m%d_%H%M%S")
        artifact_dir = ARTIFACTS_DIR / artifact_type / f"{date}_{slug}"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Détecte les fichiers multiples (séparateur ## FILE:)
        files = self._split_files(code)
        if len(files) > 1:
            for fname, fcontent in files.items():
                (artifact_dir / fname).write_text(fcontent, encoding="utf-8")
        else:
            # Fichier unique — déduit l'extension
            ext = self._infer_extension(artifact_type, code)
            (artifact_dir / f"main{ext}").write_text(code, encoding="utf-8")

        # README automatique
        readme = f"# Artifact : {task[:80]}\n\n"
        readme += f"- **Type** : {artifact_type}\n"
        readme += f"- **Créé** : {date}\n"
        readme += f"- **Fichiers** : {', '.join(files.keys()) if len(files) > 1 else f'main{ext}'}\n"
        (artifact_dir / "README.md").write_text(readme, encoding="utf-8")

        return artifact_dir

    def _split_files(self, code: str) -> dict:
        """Divise le code si plusieurs fichiers détectés avec ## FILE:"""
        pattern = r"##\s*FILE:\s*(\S+)"
        parts = re.split(pattern, code)
        if len(parts) <= 1:
            return {"single": code}
        files = {}
        for i in range(1, len(parts), 2):
            fname = parts[i].strip()
            content = parts[i + 1].strip() if i + 1 < len(parts) else ""
            files[fname] = content
        return files

    def _infer_extension(self, artifact_type: str, code: str) -> str:
        ext_map = {
            "firmware": ".py",
            "simulation": ".urdf",
            "cad": ".py",
            "policy": ".py",
            "report": ".md",
        }
        if "```python" in code or "import " in code or "def " in code:
            return ".py"
        if "<robot" in code or "<link" in code:
            return ".urdf"
        if "#!/" in code:
            return ".sh"
        return ext_map.get(artifact_type, ".txt")

    def _save_to_mea(self, task: str, artifact_type: str, artifact_path: Path) -> None:
        """Crée une entrée MEA pour l'artifact produit."""
        entry = MemoryEntry(
            id=str(uuid.uuid4())[:8],
            type="code_artifact",
            scope=artifact_type,
            context={"task": task[:120], "path": str(artifact_path)},
            summary=f"[{artifact_type}] {task[:80]}",
            details=f"Artifact sauvegardé dans {artifact_path}",
            links=[str(artifact_path)],
            importance="high",
            created_at=datetime.utcnow().isoformat(),
        )
        self.store.save_entry(entry)
        logger.debug(f"[ClaudeCode] entrée MEA créée : {entry.summary[:60]}")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def extract_code_task(plan: str | dict) -> Optional[tuple[str, str]]:
    """
    Extrait une CODE_TASK d'un plan.
    Retourne (task_description, artifact_type) ou None si pas de CODE_TASK.

    Format supporté dans le plan :
      "CODE_TASK: [firmware] Description de la tâche"
      "CODE_TASK: Description sans type"
    """
    text = plan if isinstance(plan, str) else json.dumps(plan)
    match = re.search(
        r"CODE_TASK:\s*(?:\[(\w+)\]\s*)?(.+?)(?:\n|$)",
        text, re.IGNORECASE
    )
    if not match:
        return None
    artifact_type = (match.group(1) or "misc").lower()
    if artifact_type not in ARTIFACT_TYPES:
        artifact_type = "misc"
    task_desc = match.group(2).strip()
    return task_desc, artifact_type
