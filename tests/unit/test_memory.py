"""
Unit tests for app/agent/memory/*.py.

short_term and summarizer tests use real Redis (redis_client fixture).
long_term tests use a real Chroma EphemeralClient but swap in a fake
embedding function, since this sandbox/CI may not have network access to
download the real sentence-transformers model from Hugging Face — the fake
function still exercises Chroma's actual add/query/delete/filter logic, it
just doesn't produce semantically meaningful vectors.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import app.agent.memory.long_term as long_term
import app.agent.memory.summarizer as summarizer
from app.agent.memory.short_term import append_message, clear_thread, get_recent_messages


class FakeEmbeddingFunction:
    """Deterministic, network-free stand-in for the real sentence-transformers
    embedding function, for testing Chroma plumbing rather than embedding quality."""

    def __call__(self, input):
        return [[float(hash(t) % 1000) / 1000, float(len(t)) / 100] for t in input]

    def embed_query(self, input):
        return self(input)

    def embed_documents(self, input):
        return self(input)

    def name(self):
        return "fake"


@pytest.fixture
def fake_chroma_collection():
    import uuid

    import chromadb

    client = chromadb.EphemeralClient()
    # A unique name per test — chromadb caches its underlying System by
    # settings, so two EphemeralClient() instances can end up sharing data
    # if they get_or_create the same collection name.
    collection = client.get_or_create_collection(
        name=f"test_memory_{uuid.uuid4().hex}", embedding_function=FakeEmbeddingFunction()
    )
    with patch.object(long_term, "_get_collection", return_value=collection):
        yield collection


class TestShortTermMemory:
    async def test_append_and_retrieve_round_trip(self, redis_client):
        thread_id = "pytest:short-term-1"
        await clear_thread(thread_id)

        await append_message(thread_id, HumanMessage(content="Plan a trip to Kyoto"))
        await append_message(thread_id, AIMessage(content="How many days?"))
        await append_message(thread_id, HumanMessage(content="5 days in October"))

        history = await get_recent_messages(thread_id, limit=10)

        assert len(history) == 3
        assert isinstance(history[0], HumanMessage)
        assert isinstance(history[1], AIMessage)
        assert history[2].content == "5 days in October"

    async def test_get_recent_messages_respects_limit(self, redis_client):
        thread_id = "pytest:short-term-2"
        await clear_thread(thread_id)

        for i in range(5):
            await append_message(thread_id, HumanMessage(content=f"message {i}"))

        limited = await get_recent_messages(thread_id, limit=2)
        assert len(limited) == 2
        assert limited[-1].content == "message 4"


class TestLongTermMemory:
    def test_add_and_search_scoped_to_user(self, fake_chroma_collection):
        long_term.add_fact("user-a", "Prefers window seats on long flights.")
        long_term.add_fact("user-b", "This fact belongs to a different user.")

        results = long_term.search_facts("user-a", "seating preference", k=3)

        assert results == ["Prefers window seats on long flights."]

    def test_delete_removes_fact(self, fake_chroma_collection):
        fact_id = long_term.add_fact("user-a", "Allergic to shellfish.")
        assert long_term.search_facts("user-a", "allergy", k=3) == ["Allergic to shellfish."]

        long_term.delete_fact(fact_id)

        assert long_term.search_facts("user-a", "allergy", k=3) == []


class TestSummarizer:
    async def test_below_trigger_threshold_returns_none_without_llm_call(self, redis_client, monkeypatch):
        thread_id = "pytest:summarizer-short"
        await clear_thread(thread_id)
        await append_message(thread_id, HumanMessage(content="hi"))

        mock_get_model = MagicMock()
        monkeypatch.setattr(summarizer, "get_chat_model", mock_get_model)

        result = await summarizer.maybe_summarize(thread_id)

        assert result is None
        mock_get_model.assert_not_called()

    async def test_above_trigger_threshold_summarizes_and_persists(self, redis_client, monkeypatch):
        thread_id = "pytest:summarizer-long"
        await clear_thread(thread_id)
        for i in range(summarizer.SUMMARY_TRIGGER_TURNS + 2):
            await append_message(thread_id, HumanMessage(content=f"message {i}"))

        fake_model = MagicMock()
        fake_model.ainvoke = AsyncMock(return_value=AIMessage(content="Summary of the conversation."))
        monkeypatch.setattr(summarizer, "get_chat_model", lambda config: fake_model)

        result = await summarizer.maybe_summarize(thread_id)

        assert result == "Summary of the conversation."
        stored = await summarizer.get_summary(thread_id)
        assert stored == "Summary of the conversation."