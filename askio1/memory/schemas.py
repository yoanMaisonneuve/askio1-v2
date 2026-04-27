"""
schemas.py — Structures de données MEA
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class MemoryEntry:
    id: str
    type: str               # rule | fact | decision | experiment | pattern | invariant
    scope: str              # mission | module | robot | joint | vision | control
    context: Dict
    summary: str
    details: str
    links: List[str]
    importance: str         # low | medium | high | critical
    created_at: str
    last_used_at: Optional[str] = None
    usage_count: int = 0


@dataclass
class MissionState:
    mission_id: str
    goals: List[str]
    current_status: str
    key_rules: List[str]
    open_problems: List[str]
    next_actions: List[str]
    cycle: int = 0
