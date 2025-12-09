import os
import numpy as np
import pyarrow as pa
import lancedb
from lancedb import connect
from sentence_transformers import SentenceTransformer

DB_DIR = "agent_carter_lancedb"
MODEL_NAME = "all-MiniLM-L6-v2"

_model = None


# -------------------------------------------------
# MODEL LOADING
# -------------------------------------------------
def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed(texts):
    m = _get_model()
    vecs = m.encode(texts, convert_to_numpy=True)
    return vecs.astype(np.float32)


def embed_query(text: str):
    return embed([text])[0].tolist()


# -------------------------------------------------
# LANCE DB SCHEMA
# -------------------------------------------------
def lancedb_schema(dim=384):
    return pa.schema([
        ("id", pa.string()),
        ("profile_summary", pa.string()),
        ("meta", pa.struct([
            ("name", pa.string()),
            ("headline", pa.string()),
            ("linkedin", pa.string()),
            ("profile_summary", pa.string()),    # ← REQUIRED BY db_ops
        ])),
       ("vector", pa.list_(pa.float32(), list_size=384))

    ])


# -------------------------------------------------
# DB HANDLE
# -------------------------------------------------
_db = None

def _get_db():
    global _db
    if _db is None:
        os.makedirs(DB_DIR, exist_ok=True)
        _db = connect(DB_DIR)
    return _db


# -------------------------------------------------
# GET OR CREATE TABLE
# -------------------------------------------------

def get_contacts_table(user_id=None):
    db = lancedb.connect(DB_DIR)

    table_name = f"{user_id}_contacts" if user_id else "contacts"
    schema = lancedb_schema()

    # If missing → CREATE TABLE
    if table_name not in db.table_names():
        print(f"[LanceDB] Creating new table: {table_name}")
        return db.create_table(table_name, schema=schema)

    # If exists → RETURN table
    return db.open_table(table_name)
