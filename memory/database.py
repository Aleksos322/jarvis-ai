from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base # Zaraz to stworzymy
from config.settings import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    import storage.models # Import tutaj, żeby uniknąć kołowego importu
    Base.metadata.create_all(bind=engine)