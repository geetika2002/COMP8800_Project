# database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from model import Base

DATABASE_URL = "sqlite:///./events.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db():
    Base.metadata.create_all(bind=engine)
