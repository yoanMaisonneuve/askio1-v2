"""
llm_client.py — Interface LLM abstraite
"""
import os
import anthropic


class LLMClient:
    def __init__(self, config: dict):
        self.config = config.get("llm", {})
        self.model  = os.getenv("LLM_MODEL", self.config.get("model", "claude-haiku-4-5-20251001"))
        self.max_tokens = self.config.get("max_tokens", 4096)
        self.temperature = self.config.get("temperature", 0.3)
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def call(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text.strip()
