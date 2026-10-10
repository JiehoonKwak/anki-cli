# Project-memory clean status

## Docs pass 2026-10-10: memory index

Scope: `clean docs` on project memory (`STATE.md`, `AGENTS.md`, `README.md`,
`docs/` and adjacent guides) under the 2026-10-10 contract in the shared global
`AGENTS.md` (Project Memory): `STATE.md` is an index near 60 lines; reasons,
corrections and verified results live in topic owners. Reviewed and applied in
commit `94579c6`; `STATE.md` is now 34 lines. Method: one Codex `gpt-6.1-sol`
agent per project, reviewed by Claude for docs-only scope, link/anchor validity
and retention of removed identifiers. Receipt: [review.md](review.md#d-20261010-memory-index).

Open after this pass:

5. **Limits and verification:** No clearly human-authored passage was identified; all substantive rules were retained. `.agents/clean/` audit records could not be updated because that directory is read-only. The excluded `inventory.json` remained untouched.

All **20 relative links and anchors resolve**, and `git diff --check` passes. Only the three documentation files changed; no builds, tests, collection operations or Git mutations were performed.

Reopen when `STATE.md` grows well past 60 lines, gains dated narration, or a
fact appears there without a topic owner. Earlier sections below record prior
passes.

Independent docs-only review passed all 8 questions; parent comparison accepted the reasons, corrections and explicit unknowns. Scoped delivery is recorded in the private receipt.

Living audit owner. Status: authorized documentary work applied 2026-10-08;
independent reading review pending. The earlier audit is historical input, not
pending approval for the work already applied.

The public [README](../../README.md) remains the concise installation/start
owner, with its English body under 300 characters. [AGENTS](../../AGENTS.md)
routes to [STATE](../../STATE.md), operations and the dated architecture decision.
The substantive owners explain headless access, retained queue/drain, runtime
privacy, sync separation, actual-deck verification and behavioral gap analysis.

Local prior-audit input `inventory.json` records the earlier discovery snapshot;
it is not a portable project owner. Raw history, source-review coverage and
backups belong in private run receipts. [Review](review.md) records the applied
finding and limits. Reopen affected claims when backend, runtime-root, public
release/privacy requirements or command behavior change.
