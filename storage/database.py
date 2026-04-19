# storage/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base # Dodano declarative_base

DATABASE_URL = "mysql+pymysql://jarvis_db_user:Start$123@localhost:3306/jarvis_db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# To jest baza, po której będą dziedziczyć wszystkie modele
Base = declarative_base()

def init_db():
    import storage.models  # Importujemy modele wewnątrz funkcji
    Base.metadata.create_all(bind=engine)
    print("✅ Baza danych zainicjalizowana.")