"""
api.py — Askio1 v2 REST API (Phase 6a)
======================================
Expose le système cognitif via HTTP.

Endpoints :
  POST /chat          — envoie un message, reçoit la réponse complète
  GET  /stats         — stats MEA courantes
  GET  /memory?q=...  — requête directe dans la MEA (TF-IDF)
  GET  /session       — état de la session courante
  POST /session/reset — réinitialise la session (garde la MEA)
  GET  /health        — healthcheck

Usage :
  python api.py              # démarre sur 0.0.0.0:8000
  python api.py --port 9000  # port personnalisé

Exemple curl :
  curl -X POST http://localhost:8000/chat \
       -H "Content-Type: application/json" \
       -d '{"message": "Qu'\''est-ce qu'\''une MEA ?"}'
"""

import argparse
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from askio1.agents.executor import Executor
from askio1.agents.memory_agent import MemoryAgent
from askio1.agents.observer import Observer
from askio1.agents.reviewer import Reviewer
from askio1.agents.thinker import Thinker
from askio1.cognitive_loop import CognitiveLoop
from askio1.memory.store import MemoryStore
from askio1.tools.llm_client import LLMClient

# ─── Logging ─────────────────────────────────────────────────────────────────
Path("data/logs").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    handlers=[
        logging.FileHandler(
            f"data/logs/api_{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8",
        )
    ],
)
logger = logging.getLogger("askio1.api")


# ─── Schémas Pydantic ────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None   # optionnel — généré si absent


class ChatResponse(BaseModel):
    session_id:  str
    cycle:       int
    response:    str
    verdict:     str
    elapsed_s:   float
    consolidated: bool


class MemoryResult(BaseModel):
    query:   str
    results: str
    count:   int


class SessionState(BaseModel):
    session_id:    str
    cycle:         int
    success_rate:  float
    failure_rate:  float
    mea_entries:   int
    cold_ctx_loaded: bool


class HealthResponse(BaseModel):
    status:      str
    mea_entries: int
    retrieval:   str
    version:     str = "2.0.0-phase6a"


# ─── État global (singleton par processus) ───────────────────────────────────

class AppState:
    def __init__(self):
        self.config   = None
        self.llm      = None
        self.store    = None
        self.observer = None
        self.thinker  = None
        self.executor = None
        self.reviewer = None
        self.mem_agent= None
        self.cloop    = None
        self.session_id   = f"api_{datetime.now().strftime('%H%M%S')}"
        self.cycle        = 0
        self.cold_ctx_loaded = False
        self.session_log  = []

    def boot(self):
        self.config   = yaml.safe_load(open("config.yaml", encoding="utf-8"))
        self.llm      = LLMClient(self.config)
        self.store    = MemoryStore(self.config)
        self.observer = Observer(self.llm, self.store)
        self.thinker  = Thinker(self.llm)
        self.executor = Executor(self.llm, self.store)
        self.reviewer = Reviewer(self.llm)
        self.mem_agent= MemoryAgent(self.llm, self.store)
        self.cloop    = CognitiveLoop(self.store, self.llm)
        cold = self.cloop.cold_start()
        self.cold_ctx_loaded = bool(cold)
        logger.info(f"[API] démarré — session {self.session_id} | cold_start={self.cold_ctx_loaded}")

    def reset_session(self):
        """Réinitialise la session sans vider la MEA."""
        self.session_id  = f"api_{datetime.now().strftime('%H%M%S')}"
        self.cycle       = 0
        self.session_log = []
        self.cloop       = CognitiveLoop(self.store, self.llm)
        cold = self.cloop.cold_start()
        self.cold_ctx_loaded = bool(cold)
        logger.info(f"[API] session réinitialisée → {self.session_id}")


app_state = AppState()


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    app_state.boot()
    yield
    # Shutdown : sauvegarde la session
    if app_state.cycle > 0:
        app_state.mem_agent.reflect(mission_id=app_state.session_id)
        app_state.cloop.session_end(app_state.session_id, app_state.session_log)
        logger.info("[API] session sauvegardée à l'arrêt")


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Askio1 v2 API",
    description="Système cognitif multi-agents avec MEA, boucle cognitive et TF-IDF retrieval.",
    version="2.0.0-phase6a",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
def health():
    stats = app_state.store.stats()
    from askio1.memory.store import _TFIDF_AVAILABLE
    return HealthResponse(
        status="ok",
        mea_entries=stats["total_entries"],
        retrieval="tfidf" if _TFIDF_AVAILABLE else "keyword",
    )


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message vide")

    s = app_state
    s.cycle += 1
    t0 = time.time()

    logger.info(f"[API /chat] cycle={s.cycle} msg={req.message[:80]}")

    try:
        adaptive_ctx = s.cloop.cycle_start(s.cycle, req.message)
        obs          = s.observer.observe(
            raw_text=req.message,
            context={"cycle": s.cycle, "session": s.session_id},
        )
        snippets  = s.store.retrieve_relevant(req.message)
        enriched  = f"{adaptive_ctx}\n\n[MEA]\n{snippets}" if adaptive_ctx else snippets
        plan      = s.thinker.plan({"mission_id": s.session_id}, req.message, enriched)
        result    = s.executor.execute(plan=plan, context={"cycle": s.cycle})
        review    = s.reviewer.review(result=result, goal=req.message, context={"cycle": s.cycle})
        verdict   = review.get("verdict", "?") if isinstance(review, dict) else "?"
        issues    = review.get("issues", []) if isinstance(review, dict) else []

        s.mem_agent.build_entries(
            observer_output=obs,
            context={"cycle": s.cycle, "review": review},
        )
        consolidated = s.cloop.cycle_end(
            s.cycle, verdict, issues,
            len(obs.get("candidates_for_memory", [])),
        )

        elapsed = round(time.time() - t0, 2)
        s.session_log.append({
            "cycle": s.cycle, "message": req.message,
            "response": result, "verdict": verdict,
        })

        logger.info(f"[API /chat] cycle={s.cycle} verdict={verdict} elapsed={elapsed}s")
        return ChatResponse(
            session_id   = s.session_id,
            cycle        = s.cycle,
            response     = result,
            verdict      = verdict,
            elapsed_s    = elapsed,
            consolidated = consolidated,
        )

    except Exception as e:
        logger.error(f"[API /chat] erreur cycle={s.cycle}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memory", response_model=MemoryResult)
def memory(q: str = Query(default="système cognitif", description="Requête TF-IDF dans la MEA"),
           n: int = Query(default=5, ge=1, le=20, description="Nombre de résultats")):
    snippets = app_state.store.retrieve_relevant(q, max_results=n, max_chars=4000)
    count    = len([l for l in snippets.splitlines() if l.strip()])
    return MemoryResult(query=q, results=snippets, count=count)


@app.get("/stats")
def stats():
    mea   = app_state.store.stats()
    perf  = app_state.cloop.stats.summary()
    return {
        "session_id":   app_state.session_id,
        "cycle":        app_state.cycle,
        "mea":          mea,
        "performance":  perf,
        "cold_ctx":     app_state.cold_ctx_loaded,
    }


@app.get("/session", response_model=SessionState)
def session_state():
    perf  = app_state.cloop.stats.summary()
    stats = app_state.store.stats()
    return SessionState(
        session_id      = app_state.session_id,
        cycle           = app_state.cycle,
        success_rate    = perf["success_rate"],
        failure_rate    = perf["failure_rate"],
        mea_entries     = stats["total_entries"],
        cold_ctx_loaded = app_state.cold_ctx_loaded,
    )


@app.post("/session/reset")
def reset_session():
    app_state.reset_session()
    return {"status": "ok", "new_session_id": app_state.session_id}


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(f"\n🧠 Askio1 v2 API — http://{args.host}:{args.port}")
    print(f"   Docs : http://localhost:{args.port}/docs\n")

    uvicorn.run(
        "api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
    )
