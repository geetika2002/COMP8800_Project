# models.py
from sqlalchemy import Column, String, Integer, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    session_id = Column(String, nullable=True)
    src_ip = Column(String, nullable=True)
    src_port = Column(Integer, nullable=True)
    dest_service = Column(String, nullable=True)
    username = Column(String, nullable=True)
    command = Column(String, nullable=True)
    metadata = Column(Text, nullable=True)
