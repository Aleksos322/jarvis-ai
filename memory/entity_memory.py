import json
from pathlib import Path
from typing import List, Optional


class EntityMemory:
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.items: List[str] = self._load()

    def _load(self) -> List[str]:
        if not self.file_path.exists():
            self.file_path.write_text("[]", encoding="utf-8")
            return []

        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [self._clean_text(item) for item in data if self._clean_text(item)]
            return []
        except Exception:
            return []

    def _save(self) -> None:
        self.file_path.write_text(
            json.dumps(self.items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _clean_text(self, text: str) -> str:
        return " ".join(str(text).strip().split())

    def add(self, fact: str) -> bool:
        fact = self._clean_text(fact)
        if not fact:
            return False

        if fact not in self.items:
            self.items.append(fact)
            self.items = self.items[-100:]
            self._save()
            return True

        return False

    def remove(self, fact: str) -> bool:
        fact = self._clean_text(fact)
        if fact in self.items:
            self.items.remove(fact)
            self._save()
            return True
        return False

    def clear(self) -> None:
        self.items = []
        self._save()

    def get_all(self) -> List[str]:
        return self.items[:]

    def get_context(self) -> str:
        if not self.items:
            return ""

        lines = ["Known user facts:"]
        for item in self.items:
            lines.append(f"- {item}")
        return "\n".join(lines)

    def find(self, query: str) -> List[str]:
        query = self._clean_text(query).lower()
        if not query:
            return []

        return [item for item in self.items if query in item.lower()]