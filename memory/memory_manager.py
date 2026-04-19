from storage.database import SessionLocal  # Zmienione z ..storage
from storage.models import Conversation, MemoryEntity, EpisodicSummary # To zostaje
from sqlalchemy import desc

class MemoryManager:
    def __init__(self):
        self.db = SessionLocal()

    # --- ZAPISYWANIE ---
    def save_message(self, role: str, content: str):
        """Zapisuje wiadomość do historii (Długa pamięć)"""
        msg = Conversation(role=role, content=content)
        self.db.add(msg)
        self.db.commit()

    def update_user_fact(self, key: str, value: str):
        """Zapisuje lub aktualizuje fakt o użytkowniku (Entity Memory)"""
        entity = self.db.query(MemoryEntity).filter_by(key=key).first()
        if entity:
            entity.value = value
        else:
            entity = MemoryEntity(key=key, value=value)
            self.db.add(entity)
        self.db.commit()

    # --- POBIERANIE KONTEKSTU ---
    def get_short_term_context(self, limit=15):
        """Pobiera ostatnie X wiadomości dla zachowania płynności"""
        messages = self.db.query(Conversation).order_by(desc(Conversation.timestamp)).limit(limit).all()
        # Odwracamy, żeby były chronologicznie
        return [{"role": m.role, "content": m.content} for m in reversed(messages)]

    def get_recent_messages(self, limit=10):
        """Zwraca ostatnie `limit` obiektów Conversation w porządku chronologicznym (stare->nowe)."""
        messages = self.db.query(Conversation).order_by(desc(Conversation.timestamp)).limit(limit).all()
        return list(reversed(messages))

    def get_all_user_facts(self):
        """Pobiera wszystko, co Jarvis wie o Tobie"""
        facts = self.db.query(MemoryEntity).all()
        return {f.key: f.value for f in facts}

    # --- MAGIA: BUDOWANIE PROMPTU ---
    def build_system_prompt(self):
        """Tworzy gigantyczny prompt systemowy dla Gemini Live"""
        facts = self.get_all_user_facts()
        facts_str = "\n".join([f"- {k}: {v}" for k, v in facts.items()]) if facts else "Brak znanych faktów."

        system_instruction = f"""
Jesteś Jarvisem, zaawansowanym asystentem AI. 
Twoja osobowość: inteligentny, pomocny, z lekkim poczuciem humoru.

CO WIESZ O UŻYTKOWNIKU:
{facts_str}

INSTRUKCJE:
1. Odpowiadaj naturalnie i zwięźle.
2. Jeśli użytkownik poda nowy fakt o sobie, zapamiętaj go.
3. Odnoś się do historii rozmowy, jeśli to istotne.
"""
        return system_instruction

    def close(self):
        self.db.close()