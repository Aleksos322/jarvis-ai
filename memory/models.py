from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class MemoryEntity(Base):
    """To zastąpi jarvis_memory.json (Fakty o Tobie)"""
    __tablename__ = "entities"
    id = Column(Integer, primary_key=True)
    key = Column(String(255), unique=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow)

class Conversation(Base):
    """To zastąpi conversations.json (Długa historia)"""
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True)
    role = Column(String(50)) # 'user' / 'assistant'
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)