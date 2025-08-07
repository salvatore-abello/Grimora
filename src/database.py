from fastapi import Depends
from sqlmodel import Field, Session, SQLModel, create_engine, select

from typing import Annotated
from datetime import datetime

from . import config
from .models import TranscriptInfo

engine = create_engine(config.DATABASE_URL)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

SessionDep = Annotated[Session, Depends(get_session)]