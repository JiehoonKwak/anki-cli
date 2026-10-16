# Anki CLI state

Updated: 2026-10-16 (Asia/Seoul)

## Current goal

Provide local queued note upserts through the pinned official Anki library,
without opening Anki Desktop or placing personal card state in the code repository.

## Active work

No active implementation task is recorded. Operational workflows and recovery
are owned by [operations](docs/operations.md).

## Decisions in force

- [.ctxdata.json](.ctxdata.json) declares no retained project-data payload; private collections, queue, ledger and media stay with their existing runtime owners.

- Use headless-only access without a Desktop fallback — [architecture decision](docs/decisions/2026-10-01-headless-local-queue.md).
- Retain local enqueue/drain so pending intent survives a busy collection — [queue rationale](docs/decisions/2026-10-01-headless-local-queue.md).
- Git distributes code only; queue and ledger use a private runtime root — [runtime ownership](docs/operations.md#queue-states-and-retries).
- Live `ExternalID` in the selected notetype is the upsert authority; duplicate matches fail — [identity and recovery](docs/operations.md#queue-states-and-retries).
- Verify local application and requested sync separately; full sync needs an explicit direction — [verification](docs/operations.md#verify-application-and-sync-separately).
- Gap telemetry supports concept-gap hypotheses; marked/flagged cleanup and edits are separate workflows — [gap boundary](docs/operations.md#gap-analysis-boundary).

## Blockers and open questions

No project blocker or open product question is recorded. Readiness, live collection
contents, account sync and external scheduler status need task-specific observations
([operations](docs/operations.md)).

## Next step

For the next authorized operational task, establish the intended local profile,
exclusive collection ownership, pending intent and live identity before mutation;
verify the actual result and requested sync separately ([operations](docs/operations.md)).
