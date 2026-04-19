# storage/models.py
from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from storage.database import Base  # Importujemy Base z database.py!

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(50))
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

class MemoryEntity(Base):
    __tablename__ = "entities"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), unique=True, index=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class EpisodicSummary(Base):
    __tablename__ = "summaries"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)