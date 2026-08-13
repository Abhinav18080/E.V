"""
Rolling conversation summarizer — keeps long threads from blowing up the
model's context window by periodically collapsing older turns into a short
running summary, stored in Redis alongside the raw buffer (short_term.py).

Call maybe_summarize() after appending each turn (e.g. from
app/agent/graph.py's start_turn); it's a cheap no-op below
SUMMARY_TRIGGER_TURNS, so it's safe to call unconditionally.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from app.agent.memory.short_term import get_recent_messages
from app.config import get_settings
from app.redis_client import get_redis_client

SUMMARY_KEY_PREFIX = "thread_summary:"
SUMMARY_TRIGGER_TURNS = 20  # start summarizing once a thread has this many messages
KEEP_RECENT_TURNS = 6  # always leave the most recent N messages out of the summary

SUMMARIZE_PROMPT = (
    "Summarize the conversation so far in a few sentences. Preserve concrete "
    "facts, decisions, and preferences the user mentioned (dates, names, "
    "places, choices already made) — this summary will replace the full "
    "history for context purposes, so don't drop anything load-bearing."
)


def _summary_key(thread_id: str) -> str:
    return f"{SUMMARY_KEY_PREFIX}{thread_id}"


def _get_model() -> ChatOllama:
    settings = get_settings()
    return ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url, temperature=0)


async def get_summary(thread_id: str) -> str | None:
    redis_client = get_redis_client()
    return await redis_client.get(_summary_key(thread_id))


async def maybe_summarize(thread_id: str) -> str | None:
    """
    If the thread has grown past SUMMARY_TRIGGER_TURNS, collapse everything
    except the most recent KEEP_RECENT_TURNS messages into an updated
    summary and persist it. Returns the current summary (existing or newly
    generated), or None if the thread is still short enough that no summary
    is needed yet.
    """
    redis_client = get_redis_client()
    all_messages = await get_recent_messages(thread_id, limit=1000)
    if len(all_messages) < SUMMARY_TRIGGER_TURNS:
        return await get_summary(thread_id)

    to_condense = all_messages[:-KEEP_RECENT_TURNS] if KEEP_RECENT_TURNS else all_messages
    transcript = "\n".join(f"{m.__class__.__name__}: {m.content}" for m in to_condense)

    existing_summary = await get_summary(thread_id)
    prompt_messages = [SystemMessage(content=SUMMARIZE_PROMPT)]
    if existing_summary:
        prompt_messages.append(
            SystemMessage(
                content=f"Existing summary — extend/update it, don't discard: {existing_summary}"
            )
        )
    prompt_messages.append(HumanMessage(content=transcript))

    result = await _get_model().ainvoke(prompt_messages)
    summary = result.content

    await redis_client.set(_summary_key(thread_id), summary)
    return summary