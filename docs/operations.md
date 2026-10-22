# Operations and recovery

Living reference for the headless-only CLI. Collection commands below describe
an authorized operational workflow; they are not necessary for documentation
checks.

The CLI applies local queued note upserts through the official Anki library
pinned in [pyproject.toml](../pyproject.toml), without opening Anki Desktop.

## Select the local owner

`ANKI_CLI_COLLECTION` selects an exact existing collection. Otherwise
`ANKI_CLI_BASE` and `ANKI_CLI_PROFILE` select the local profile, with the
last-loaded or sole profile used when unambiguous. Missing/ambiguous selection
fails instead of creating an empty collection. Sync credentials come from that
profile, not a job JSON file. `ANKI_CLI_ANKI_HOST` is diagnostic metadata, not remote
execution or queue transport.

Close Anki Desktop before collection operations and keep it closed while a
headless operation owns the collection. The backend checks other-process use,
takes its own lock and requests an official backup before the first mutation.
If access fails, leave queued intent pending; do not bypass the lock or force
close another process. `ready` checks headless readiness; `ensure-anki` and the
AnkiConnect backend are retired. A network I/O timeout does not bound an entire
large media synchronization.

Obsolete `ANKI_CLI_BACKEND` values fail rather than silently falling back.

## Queue states and retries

[.ctxdata.json](../.ctxdata.json) declares no retained project-data payload.
Private cards, collections, queue jobs, ledger, media and credentials remain
with their runtime owners; Git distributes package source and synthetic fixtures.

The global `--root` option precedes the subcommand and selects the private
runtime directory containing `state/`. Enqueue and drain must use the same
root. Git updates move code, not queue jobs or attached media. A remote queue
requires separately authorized private delivery to the intended owner.

Queue, done/failed records and ledger default to `$XDG_STATE_HOME/anki-cli` when
that variable is absolute, otherwise `~/.local/state/anki-cli`. Keep private
history and personal operating data out of every new public commit, not just
the current tree.

- `pending`: validated intent awaits application. Drain obtains collection
  access before iterating jobs, so a busy collection leaves jobs pending.
- `done`: local application completed and a result was recorded. Inspect
  `deck_move.ok` and the actual cards before treating the requested deck as
  verified.
- `failed`: a job failed validation/application and retains its input and error.
  A backend operation may have made partial changes before failing; inspect live
  notes before retrying it.

Reuse a stable `ExternalID` for the same logical note. For interrupted work,
compare queue state, ledger and `find --live --external-id` against the actual
collection. A ledger entry alone does not prove that a note still exists or
that its content/deck is correct. Avoid generating a new ID merely to retry.
Live `ExternalID` matches in the selected notetype identify the upsert; duplicate
matches fail instead of choosing one arbitrarily.

`drain --dry-run` validates queued work without opening the collection. Other
commands' dry runs can still open/read the collection; check the particular
command before using it as a no-access check.

## Verify application and sync separately

Read the resulting note fields, card IDs and actual `deckName`; for a deck move,
retain note/card identity and scheduling rather than recreating the note.
Upsert reads generated cards and attempts a move when their deck differs from
the requested deck; inspect `deck_move.ok` and the actual cards afterward.
`move_cards_to_deck` compares type, queue, due, interval, reps and lapses as well
as card/note identity. Check its reported errors.

With `drain --sync`, inspect `sync.ok`: top-level `ok` and the exit code reflect
job failures and can indicate success while sync failed. Applied jobs remain in
`done`; use `sync` for recovery instead of enqueuing duplicate cards. Normal
collection and media sync reuse profile authentication and follow the returned
endpoint. A required full sync stops for an explicit upload/download decision;
never infer the direction or cross-device completion from local application.

## Cleanup lessons

A field update, tag removal, flag clear and sync are separate operations. If a
later step fails, re-read the current fields and remaining markers before
repeating earlier work. Marked tags and numeric card flags are different
selectors; clear only the requested set. When counts exceed expectation, inspect
`clear --dry-run`, then verify the remaining live matches after the authorized
clear. Verbose returned IDs or a completion message alone are insufficient.

Repair content in place when possible so learned scheduling survives. If an
imported `>>>` delimiter or explanation heading became a bogus card, inspect the
source formatting as well as the card; changing the import source needs its own
scope. For a split, preserve the appropriate existing card and suspend/archive
an overloaded predecessor unless deletion was requested.

## Gap analysis boundary

`gap export` reads review telemetry; `--sync-first` additionally performs sync.
It supplies candidate evidence rather than a diagnosis or automatic edits.
Repeated Again/Hard, maturity, lapses and lightweight source/tag/text clusters
help distinguish missing intermediate concepts, confusable pairs, narrow
examples and cue problems. A single new-card failure or broad backlog does not
establish a knowledge gap. Hard counts use review-type-aware button semantics:
button 2 during learning/relearning can mean Good.

Marked and flagged cleanup is a separate manual workflow. The export excludes
those selectors as candidate signals, although a selected note may still carry
such tags in its payload. Suggestions should explain the behavioral evidence
and propose bridge, distinction or example cards; applying them is a separate
operation. Scheduling a collector is outside this package, and telemetry source
availability does not prove a scheduler is currently running.

Source locators: [CLI](../src/anki_cli/cli.py),
[headless](../src/anki_cli/headless.py), [queue](../src/anki_cli/queue.py),
[gap telemetry](../src/anki_cli/gap.py).
