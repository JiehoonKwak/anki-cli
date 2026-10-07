# Anki CLI state

Living document. Source reviewed 2026-10-08 against `e9f5a05` (version 0.3.0).

## Goal and verified architecture

Provide local queued note upserts through the pinned official Anki library,
without opening Anki Desktop or placing personal card state in the code
repository. Current source has a headless-only backend, host-local queue and
ledger, native collection/media sync, deck movement, marker cleanup and
read-only gap telemetry. This describes source behavior; readiness, collection
contents, account synchronization and external schedulers require their own
observations.

## Decisions in force and reasons

- Headless-only access removes the foreground-window dependency of the former
  AnkiConnect route. A background launch flag did not remove the need for the
  app; the replacement uses Anki's own collection API. Obsolete backend values
  fail rather than silently falling back. See the
  [2026-10-01 decision](docs/decisions/2026-10-01-headless-local-queue.md).
- Keep `enqueue` and `drain`: pending intent survives a busy collection and can
  be applied later. Removing Git transport did not remove the application stage.
  Enqueue and drain must select the same private runtime root; enqueue on a
  different host is not delivery to the collection owner.
- Git distributes code only. Queue, done/failed records and ledger default to
  `$XDG_STATE_HOME/anki-cli` when that variable is absolute, otherwise
  `~/.local/state/anki-cli`. Keep private history and personal operating data out
  of every new public commit, not just the current tree.
- Stable `ExternalID` in the selected notetype identifies an upsert in the
  actual collection. The local ledger aids lookup and recovery; it is not
  authoritative deduplication. Duplicate live matches fail instead of choosing
  one arbitrarily.
- Local application and Anki synchronization are separate outcomes. A failed
  requested sync leaves applied jobs in `done`; retry sync rather than recreate
  cards. Full sync requires an explicit upload/download choice.
- Gap export supports finding missing concepts and confusable patterns, not
  automatically declaring difficult cards defective. The adopted June 21
  correction excluded marked/flagged cleanup from this behavioral analysis.
  Repeated review friction, maturity and related-card clusters inform hypotheses
  and draft bridge/distinction/example cards; edits need separate authorization.

## Lessons and next checks

A requested deck in a result was once mistaken for the cards' actual deck.
Current upsert reads generated cards and attempts a move when needed. Inspect
`deck_move.ok`, actual `deckName`, fields and scheduling before claiming success;
a top-level success alone does not establish all of those facts. Native deck
moves compare note/card identity and scheduling before and after movement.

A cleanup can partially succeed before a later marker or sync operation fails.
Re-read current matches and fields before retrying; clear only the requested
markers. Malformed imported delimiters may originate in source material, so
repairing only the generated card can allow the problem to recur. See
[operations](docs/operations.md).

For the next authorized operational task, establish the intended local profile,
collection ownership, pending intent and live identity before mutation, then
verify the actual result and requested sync separately. No current scheduler or
cross-device completion is established by the CLI source alone.
