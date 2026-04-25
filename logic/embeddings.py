import logging
import os
import numpy as np
import pyarrow as pa
import lancedb

from logic.config import get_openai_client, get_openai_embedding_model

logger = logging.getLogger(__name__)

DB_DIR = "agent_carter_lancedb_streamlitcloud"
EMBED_DIM = 1536


def embed(texts):
    """
    Returns a list of embedding vectors for a list of input strings.
    """
    model = get_openai_embedding_model()
    response = get_openai_client().embeddings.create(model=model, input=texts)
    vectors = [np.array(e.embedding, dtype=np.float32) for e in response.data]
    return np.vstack(vectors)


def embed_query(text: str):
    """
    Returns a single embedding vector for one input string.
    """
    return embed([text])[0].tolist()


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


def get_contacts_table(user_id=None):
    os.makedirs(DB_DIR, exist_ok=True)
    db = lancedb.connect(DB_DIR)

    table_name = f"{user_id}_contacts" if user_id else "contacts"
    schema = lancedb_schema()

    if table_name not in db.table_names():
        logger.info("creating lancedb table %s", table_name)
        return db.create_table(table_name, schema=schema)

    return db.open_table(table_name)
