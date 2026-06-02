# AsyncAPI note — WS `/rooms/{room_id}/stream`

**Protocol:** WebSocket (RFC 6455)
**Binding:** `ws://127.0.0.1:{port}/rooms/{room_id}/stream`

## Connect semantics (subscribe-then-replay+dedup; ADR-025 D6 R0-B Y1)

On client connect the server performs three steps **in this order** to
guarantee gap-free, duplicate-free delivery:

1. **Subscribe** — registers a bounded queue for the room on the event
   bus (every event published from this instant onward is enqueued).
2. **Replay** — reads all current events from the read-only WAL
   connection and sends them as `StreamEventMessage` frames.
3. **Replay-complete** — sends one `StreamReplayCompleteMessage` frame
   to signal that the client has seen the full historical prefix.
4. **Live stream** — drains the queue and forwards each new event as it
   arrives (events that appeared during replay are deduped by `event.id`
   so every event is delivered exactly once).

Registering before reading eliminates the window between the replay
SELECT and the subscribe call where a concurrent append would be missed.

## Server → client message shapes

All messages are JSON strings.

### `StreamEventMessage`
```json
{
  "kind": "event",
  "event": { ...Event fields... }
}
```
Sent for each event: replay phase (all historical events in order), then
live phase (each newly-appended event as it is published).

### `StreamReplayCompleteMessage`
```json
{ "kind": "replay_complete" }
```
Sent once, after all replay events. Signals that subsequent messages are
live (real-time) events only. Clients may use this to switch UI state
from "loading history" to "live".

### `StreamErrorMessage`
```json
{
  "kind": "error",
  "stage": "append" | "turn",
  "appended_event_id": "<EventId or null>",
  "reason": "<string>"
}
```
Sent when a turn fails mid-stream (mirrors `IntentError`; see below).
`stage="turn"` means the intent was already persisted — do **not** retry
the POST; reconcile via replay.

## Client → server

The WS channel is **server→client only**. The client sends no messages.
Intent (user input) is submitted via `POST /rooms/{room_id}/intent`.

## Backpressure / drop policy

Subscriber queues are bounded (512 events). A slow or disconnected
client whose queue fills is **dropped silently** — the server
unsubscribes it without blocking other subscribers or the writer.

## Partial-turn error envelope (`IntentError` / ADR-025 D5)

When a turn fails after a successful append (stage `"turn"`), the server
may emit a `StreamErrorMessage` on the subscriber channel. Clients must
treat `stage="turn"` as "intent already landed — reconcile via replay,
do not re-post." `stage="append"` means nothing was persisted and the
intent is safe to retry.
