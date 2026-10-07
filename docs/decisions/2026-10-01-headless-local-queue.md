# Headless access and a local queue

Date: 2026-10-01. Status: adopted; implemented in the current 0.3.0 architecture.

The former AnkiConnect workflow needed Anki Desktop and could bring its window
to the foreground. Adding a background launch option was insufficient because
the route already used one. The chosen replacement uses the official headless
Anki library, reuses an existing local profile, checks exclusive ownership and
backs up before writes. An automatic Desktop fallback would reintroduce the
original dependency, so the final backend is headless-only.

Headless access changes how the collection is opened. It does not make queueing
or Anki synchronization obsolete. The adopted workflow retains local enqueue
and drain so intent can wait safely when another process owns the collection;
retains the local ledger for lookup; and retains native Anki sync for account and
media synchronization. Live `ExternalID` lookup remains the upsert authority.
Git commits and pushes are unnecessary for applying a local card and were
removed from the CLI workflow.

Public release required removing personal card/state data and private ancestral
history. Keeping the old commit identities would also keep their private
parents reachable. The release therefore rebuilt a sanitized code baseline and
reconstructed the headless changes in order, followed by the runtime-local queue
change. The public lineage is `80ec694` → `4120da9` → `15ced12` → `e9f5a05`;
old private-history commit identities are not portable references in this tree.
The repository remains the single public code package, with a short English
README. Private backups and runtime data remain outside it.

Implementation locators: [headless backend](../../src/anki_cli/headless.py),
[backend selection](../../src/anki_cli/backend.py),
[queue transitions](../../src/anki_cli/queue.py) and
[CLI state-root/drain handling](../../src/anki_cli/cli.py).
