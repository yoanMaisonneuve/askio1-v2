"""
executor.py — Agent Exécuteur
Agit, génère du code, appelle des outils.
"""
import logging
from askio1.tools.llm_client import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es l'Exécuteur d'un système cognitif.
À partir d'un plan, génère le code, les scripts ou les actions nécessaires.
Sois précis, concis, et immédiatement utilisable."""


class Executor:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def execute(self, plan: dict, context: dict) -> str:
        user_prompt = f"Plan: {plan}\nContexte: {context}"
        return self.llm.call(SYSTEM_PROMPT, user_prompt)
