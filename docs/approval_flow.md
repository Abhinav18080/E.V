# Human-in-the-Loop Approval Flow

Every side-effecting action (sending an email, creating a calendar event) must be
explicitly approved by a human before it runs. This is enforced by the agent graph
itself, not left to the LLM's judgment — see `SIDE_EFFECTING_TOOLS` in
`app/agent/nodes/executor.py`.

## Intended end-to-end design

```
 POST /chat "email my friend about the trip"
        │
        ▼
   planner (decides: tool_call, email.send)
        │
        ▼
   executor  ── email.send is side-effecting, no decision yet ──▶  returns pending_approval,
        │                                                          no MCP call made
        ▼
   approval_gate ── interrupt() pauses the graph here ──▶ pending approval surfaces to
        │                                                  the caller (via LangGraph's
        │                                                  interrupt mechanism) AND gets
        │                                                  persisted to Redis so it can be
        │                                                  listed/decided independently of
        │                                                  the paused graph run
        │
        │        [ user reviews GET /approvals, decides ]
        │
        ▼
   POST /approvals/{id}/decision  ── writes the decision, then resumes
        │                              the paused thread via
        │                              app.agent.graph.resume_with_decision()
        ▼
   executor (runs again, approval_decision is now set)
        │
        ├─ approved → actually calls the MCP tool (e.g. email.send)
        └─ rejected → skips the call, records status="rejected"
        ▼
   responder (tells the user what happened)
```

## What's implemented and tested today

All three pieces are connected and covered by an end-to-end test
(`tests/integration/test_approval_loop.py`) that exercises the real path:
`POST /chat` pausing on a side-effecting tool call, the pending approval
showing up in the Redis-backed queue, deciding it resuming the paused
graph, the tool actually running (or not, if rejected), and a durable
`ApprovalRecord` row landing in the database.

- **`app/api/routes/chat.py`** calls `start_turn()` for real. If the result
  contains `__interrupt__`, it returns `pending_approval_id` instead of a
  reply.
- **`app/agent/nodes/approval_gate.py`** calls `create_pending_approval()`
  *before* calling `interrupt()`, using the same id in both the Redis queue
  entry and the payload `interrupt()` surfaces — that id is what
  `chat.py` returns as `pending_approval_id`.
- **`create_pending_approval()`** (in `app/api/routes/approvals.py`) is
  idempotent per `thread_id`, deliberately: LangGraph re-runs a node's code
  from the top on every resume, up to wherever `interrupt()` was called
  (confirmed empirically, and by `test_rejected_action_does_not_run_and_is_idempotent_to_create`)
  — without that idempotency check, every resume of a paused thread would
  create a second, duplicate approval record.
- **`decide_approval()`** updates the Redis queue entry, calls
  `app.agent.graph.resume_with_decision()` to actually resume the paused
  graph, and writes a durable `ApprovalRecord` row (`app/db/models.py`) so
  the decision survives the queue entry's TTL.

## Example: deciding a pending approval

```
POST /approvals/8e6a1e0b-.../decision
{
  "approve": true,
  "reason": null
}
```

Response:
```json
{
  "id": "8e6a1e0b-...",
  "thread_id": "thread-abc123",
  "action_type": "email.send",
  "summary": "Send an email to ['friend@example.com'] — subject: 'Trip plans'",
  "payload": { "to": ["friend@example.com"], "subject": "Trip plans", "body": "..." },
  "status": "approved",
  "created_at": "2026-08-20T12:00:00Z",
  "decided_at": "2026-08-20T12:05:00Z"
}
```

A rejection looks the same but with `"approve": false` and an optional `"reason"` —
`executor.py` uses that to tell the responder node the action was declined rather than
retrying it (see `RESPONDER_TOOL_RESULT_PROMPT` in
`app/agent/prompts/tool_use_prompt.py`).

## Durable audit trail

`app/db/models.py`'s `ApprovalRecord` table holds a permanent record of
every approval decision, outliving the Redis queue's TTL (currently 3 days
— see `APPROVAL_TTL_SECONDS` in `approvals.py`). `decide_approval()` writes
a row here (via `_record_approval_decision`, run through `asyncio.to_thread`
since it's a synchronous SQLAlchemy session) in the same request that
resumes the graph, so the two stay in sync.

## Why a queue *and* an interrupt, rather than just one

It would be simpler to only have the graph-side interrupt and let the client poll
`graph.aget_state()` directly. The Redis-backed queue exists on top of that because:
- It gives a normal REST surface (`GET /approvals`) for a frontend to render a "things
  waiting on you" list, without needing to understand LangGraph's checkpoint internals.
- It's queryable across *all* of a user's paused threads at once, rather than one at a
  time by thread id.
- It can carry a TTL and a durable audit record independent of how long the graph's
  checkpointer happens to retain a given thread's state.