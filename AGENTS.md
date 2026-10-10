# Anki CLI agent guide

Read [STATE.md](STATE.md) for current work and the decision index, then
[operations](docs/operations.md) for queue recovery, collection ownership and
verification. [README.md](README.md) owns installation and the concise public
introduction; keep its English body under 300 characters.

- This is the public code repository. Keep card contents, queue/ledger data,
  collection files, credentials, personal operating instructions and private
  history outside Git. Use synthetic fixtures for development.
- Use the official headless backend; do not add automatic Desktop launch,
  AnkiConnect fallback, force-close behavior or automatic full-sync direction.
- Collection operations require the intended local profile and exclusive
  ownership. Enqueue records intent; it does not prove application or remote
  delivery. Read actual cards and the separate sync result before reporting an
  authorized operation complete.
- [pyproject.toml](pyproject.toml) and [uv.lock](uv.lock) own packaging and pinned
  dependencies; [src/anki_cli](src/anki_cli) owns behavior and [tests](tests)
  contains isolated fixtures. Documentation work does not require opening a
  collection, draining jobs or syncing an account.
- Personal study conventions and agent approval policies belong to the invoking
  workflow, not this public package. Preserve the requested scope when using
  search, clear, move or telemetry commands.
