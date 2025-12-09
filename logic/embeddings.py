import os
import numpy as np
import pyarrow as pa
import lancedb
from lancedb import connect
from openai import OpenAI

DB_DIR = "agent_carter_lancedb_streamlitcloud"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536   # OpenAI embedding dimension

# OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# -------------------------------------------------
# MODEL LOADING — not needed for OpenAI but kept for API symmetry
# -------------------------------------------------
def _get_model():
    return EMBED_MODEL


# -------------------------------------------------
# EMBEDDINGS
# -------------------------------------------------
def embed(texts):
    """
    Returns a list of embedding vectors for a list of input strings.
    """
    response = client.embeddings.create(
        model=EMBED_MODEL,
        input=texts
    )
    vectors = [np.array(e.embedding, dtype=np.float32) for e in response.data]
    return np.vstack(vectors)


def embed_query(text: str):
    """
    Returns a single embedding vector for one input string.
    """
    return embed([text])[0].tolist()


# -------------------------------------------------
# LANCE DB SCHEMA (UPDATED for dim=1536)
# -------------------------------------------------
def lancedb_schema(dim=EMBED_DIM):
    return pa.schema([
        ("id", pa.string()),
        ("profile_summary", pa.string()),
        ("meta", pa.struct([
            ("name", pa.string()),
            ("headline", pa.string()),
            ("linkedin", pa.string()),
            ("profile_summary", pa.string()),
        ])),
        ("vector", pa.list_(pa.float32(), list_size=dim))
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

    if table_name not in db.table_names():
        print(f"[LanceDB] Creating new table: {table_name}")
        return db.create_table(table_name, schema=schema)

    return db.open_table(table_name)
