import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from config.settings import (
    ENTITY_MEMORY_FILE,
    EPISODIC_MEMORY_FILE,
    CONVERSATIONS_FILE,
    SHORT_TERM_MEMORY_LIMIT,
)
from memory.short_term import ShortTermMemory
from memory.entity_memory import EntityMemory
from memory.episodic_memory import EpisodicMemory


class MemoryManager:
    def __init__(self):
        self.short_term = ShortTermMemory()
        self.entity_memory = EntityMemory(ENTITY_MEMORY_FILE)
        self.episodic_memory = EpisodicMemory(EPISODIC_MEMORY_FILE)

    def add_interaction(self, user_text: str, ai_text: str) -> None:
        user_text = self._clean_text(user_text)
        ai_text = self._clean_text(ai_text)

        if user_text:
            self.short_term.add("user", user_text)

        if ai_text:
            self.short_term.add("assistant", ai_text)

    def add_user_message(self, text: str) -> None:
        text = self._clean_text(text)
        if text:
            self.short_term.add("user", text)

    def add_assistant_message(self, text: str) -> None:
        text = self._clean_text(text)
        if text:
            self.short_term.add("assistant", text)

    def add_entity_fact(self, fact: str) -> bool:
        return self.entity_memory.add(fact)

    def remove_entity_fact(self, fact: str) -> bool:
        return self.entity_memory.remove(fact)

    def clear_entity_memory(self) -> None:
        self.entity_memory.clear()

    def add_episodic_summary(self, summary: str, date: Optional[str] = None) -> bool:
        return self.episodic_memory.add(summary, date)

    def clear_episodic_memory(self) -> None:
        self.episodic_memory.clear()

    def clear_short_term(self) -> None:
        self.short_term.clear()

    def clear_all(self) -> None:
        self.clear_short_term()
        self.clear_entity_memory()
        self.clear_episodic_memory()

    def get_short_term_context(self) -> str:
        return self.short_term.get_context()

    def get_entity_context(self) -> str:
        return self.entity_memory.get_context()

    def get_episodic_context(self, limit: int = 5) -> str:
        return self.episodic_memory.get_context(limit)

    def build_context(self) -> str:
        parts = []

        entity_ctx = self.get_entity_context()
        if entity_ctx:
            parts.append(entity_ctx)

        episodic_ctx = self.get_episodic_context()
        if episodic_ctx:
            parts.append(episodic_ctx)

        short_ctx = self.get_short_term_context()
        if short_ctx:
            parts.append("Recent conversation:")
            parts.append(short_ctx)

        return "\n\n".join(parts).strip()

    def build_full_prompt(self, base_prompt: str) -> str:
        context = self.build_context()
        if context:
            return f"{base_prompt}\n\n{context}"
        return base_prompt

    def export_state(self) -> Dict[str, Any]:
        return {
            "short_term": self.short_term.get_messages(),
            "entity_memory": self.entity_memory.get_all(),
            "episodic_memory": self.episodic_memory.get_all(),
        }

    def _clean_text(self, text: str) -> str:
        return " ".join(str(text).strip().split())