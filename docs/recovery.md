# Run lifecycle and recovery guarantees

## API

Start the API with `uv run uvicorn aegisflow.api:app`. Create a run with a stable
client key; repeating the key returns the original run ID:

```powershell
curl.exe -X POST http://127.0.0.1:8000/v1/runs `
  -H "Content-Type: application/json" -H "Idempotency-Key: incident-42" `
  -d '{"question":"What caused the payment timeout?","top_k":3}'
curl.exe http://127.0.0.1:8000/v1/runs/<run-id>
curl.exe -N -H "Last-Event-ID: 0" http://127.0.0.1:8000/v1/runs/<run-id>/events
```

The event endpoint replays persisted events after the supplied sequence and then
waits for new events. `POST /v1/runs/{id}/resume` resumes a failed or cancelled run;
`POST /v1/runs/{id}/cancel` requests cooperative cancellation. Run records/events are
in `runtime/runs.sqlite3`, graph checkpoints are in `runtime/checkpoints.sqlite3`.
Both locations can be replaced on `app.state.run_db_path` and
`app.state.checkpoint_path` before the FastAPI lifespan starts.

## Recovery semantics

LangGraph checkpoints are keyed by the run ID. A checkpoint is written at graph
superstep boundaries, and startup requeues rows left in `queued` or `running`. Resume
continues from the last saved graph state; a node interrupted before its checkpoint
may execute again from its beginning. This is **at least once**, not exactly once.
Current workflow nodes only read local retrieval data and call the model. Any future
external write must use a stable idempotency key or an outbox/transaction before it is
safe to retry.

The SQLite saver is intended for a single local process. It does not coordinate
multiple API workers. A SQLite unique constraint arbitrates duplicate idempotency keys.
Cancellation is cooperative: it is checked at graph boundaries and before model or
retrieval calls. A synchronous local model request already in flight can finish before
the run stops. The workflow deadline is also checked between nodes; model HTTP calls
retain their own configured client timeout.

## Reproduce a crash-resume walkthrough

1. Start the API and create a run with an `Idempotency-Key`.
2. Save its ID and observe `/events` until at least one node event appears.
3. Terminate the API process, restart it with the same runtime directory, and poll the
   same run ID. Startup recovery resumes queued/running rows from the SQLite checkpoint.
4. Confirm earlier event IDs remain available and the final status/result is persisted.

The demo depends on local Ollama and the configured corpus index. This repository
contains these reproducible steps; a captured video is not included because this
workspace has no screen-recording tool available.
