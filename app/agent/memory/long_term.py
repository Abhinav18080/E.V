"""
Long-term memory — a local vector store (Chroma) for persistent facts and
preferences about the user, e.g. "prefers window seats", "usually books
morning flights". Retrieved facts get injected into AgentState["memory_context"]
ahead of the planner's LLM call (see start_turn() in app/agent/graph.py).

Runs fully local and free: Chroma persists to disk at settings.chroma_persist_dir
and embeddings are computed locally via sentence-transformers — no API calls,
no per-query cost, and it works fine offline.
"""

import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.utils import embedding_functions

from app.config import get_settings

COLLECTION_NAME = "user_memory"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"


@lru_cache
def _get_collection() -> Collection:
    settings = get_settings()
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL_NAME
    )
    return client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=embedding_fn)


def add_fact(user_id: str, text: str, metadata: dict[str, Any] | None = None) -> str:
    """
    Store a fact/preference for a user.

    TODO: call this from a dedicated memory-extraction step once one exists
    (e.g. a node that looks at a finished turn and decides what's worth
    remembering) rather than only via manual/test calls for now.
    """
    collection = _get_collection()
    fact_id = str(uuid.uuid4())
    full_metadata = {
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **(metadata or {}),
    }
    collection.add(ids=[fact_id], documents=[text], metadatas=[full_metadata])
    return fact_id


def search_facts(user_id: str, query: str, k: int = 5) -> list[str]:
    """
    Retrieve the k most relevant stored facts for this user given a query
    (typically the latest user message). Returns plain text ready to drop
    into AgentState["memory_context"].
    """
    collection = _get_collection()
    count = collection.count()
    if count == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=min(k, count),
        where={"user_id": user_id},
    )
    documents = results.get("documents") or [[]]
    return documents[0]


def delete_fact(fact_id: str) -> None:
    _get_collection().delete(ids=[fact_id])