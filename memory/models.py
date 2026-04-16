from sqlalchemy import Column, Integer, String, Text, DateTime, func
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class MemoryEntity(Base):
    __tablename__ = "entities"
    id = Column(Integer, primary_key=True)
    key = Column(String(255), unique=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True)
    role = Column(String(50)) 
    content = Column(Text)
    timestamp = Column(DateTime, default=func.now())

class EpisodicSummary(Base):
    """Pamięć epizodyczna - kondensacja wiedzy"""
    __tablename__ = "summaries"
    id = Column(Integer, primary_key=True)
    content = Column(Text)
    created_at = Column(DateTime, default=func.now())