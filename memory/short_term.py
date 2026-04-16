import json
import os
from config.settings import SHORT_TERM_MEMORY_LIMIT, CONVERSATIONS_FILE


class ShortTermMemory:
    def __init__(self):
        self.memory = []
        self._load()

    def _load(self):
        if not os.path.exists(CONVERSATIONS_FILE):
            self.memory = []
            return

        try:
            with open(CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    self.memory = data
                else:
                    self.memory = []
        except Exception:
            self.memory = []

    def _save(self):
        try:
            os.makedirs(os.path.dirname(CONVERSATIONS_FILE), exist_ok=True)
            with open(CONVERSATIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("Błąd zapisu short-term:", e)

    def add(self, role: str, text: str):
        if not text or not text.strip():
            return

        self.memory.append({
            "role": role,
            "text": text.strip()
        })

        if len(self.memory) > SHORT_TERM_MEMORY_LIMIT:
            self.memory = self.memory[-SHORT_TERM_MEMORY_LIMIT:]

        self._save()

    def get_context(self) -> str:
        lines = []
        for msg in self.memory:
            role = msg.get("role", "user")
            text = msg.get("text", "").strip()
            if not text:
                continue

            if role == "user":
                lines.append(f"User: {text}")
            else:
                lines.append(f"Jarvis: {text}")

        return "\n".join(lines)

    def get_messages(self):
        return self.memory[:]

    def clear(self):
        self.memory = []
        self._save()

    def last_user_message(self):
        for msg in reversed(self.memory):
            if msg.get("role") == "user":
                return msg.get("text")
        return None