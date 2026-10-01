# anki-cli

Create and update Anki notes from a local queue using Anki's headless library. Requires Python 3.11+, uv, and an existing profile.

Run `uv sync` and `uv run anki-cli --help`. `enqueue upsert` queues a note; `drain` applies it. Close Anki Desktop before draining.
