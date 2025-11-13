from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from .extensions import db

DATABASE_URL = "postgresql+psycopg2://postgres:admin@localhost:5432/tco_vending_cards"

engine = create_engine(DATABASE_URL, echo=False)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    # en postgres es set_client_encoding
    dbapi_connection.set_client_encoding('UTF8')

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
