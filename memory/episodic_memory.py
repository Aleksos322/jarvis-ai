import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional


class EpisodicMemory:
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.items: List[Dict[str, Any]] = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        if not self.file_path.exists():
            self.file_path.write_text("[]", encoding="utf-8")
            return []

        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                cleaned = []
                for item in data:
                    if isinstance(item, dict):
                        date = str(item.get("date", "")).strip()
                        summary = str(item.get("summary", "")).strip()
                        if summary:
                            cleaned.append({
                                "date": date or datetime.now().strftime("%Y-%m-%d"),
                                "summary": " ".join(summary.split())
                            })
                return cleaned
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

    def add(self, summary: str, date: Optional[str] = None) -> bool:
        summary = self._clean_text(summary)
        if not summary:
            return False

        item = {
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "summary": summary,
        }

        self.items.append(item)
        self.items = self.items[-50:]
        self._save()
        return True

    def clear(self) -> None:
        self.items = []
        self._save()

    def get_all(self) -> List[Dict[str, Any]]:
        return self.items[:]

    def get_recent(self, limit: int = 5) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        return self.items[-limit:]

    def get_context(self, limit: int = 5) -> str:
        recent = self.get_recent(limit)
        if not recent:
            return ""

        lines = ["Recent episode summaries:"]
        for item in recent:
            date = item.get("date", "")
            summary = item.get("summary", "")
            if summary:
                lines.append(f"- [{date}] {summary}")
        return "\n".join(lines)

    def find(self, query: str) -> List[Dict[str, Any]]:
        query = self._clean_text(query).lower()
        if not query:
            return []

        return [
            item for item in self.items
            if query in str(item.get("summary", "")).lower()
        ]