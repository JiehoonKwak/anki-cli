# Anki CLI documentary review

Independent docs-only review passed all 8 questions; parent comparison accepted the reasons, corrections and explicit unknowns. Scoped delivery is recorded in the private receipt.

Living result. Authorized documentary work applied 2026-10-08; independent
reading verification pending. Code and collection operation changes are outside
this review.

## Applied ANKICLI-01

Added a compact agent entrypoint, a substantive current-state owner, operations
and a dated October 1 architecture decision. The earlier proposal to avoid an
empty STATE remains valid: recovered decisions and failure lessons now provide
real content. The short public README remains unchanged.

The owners retain why headless-only access replaced the foreground-dependent
route, why local queue/drain and ledger survived Git removal, why sync and local
application differ, and why actual cards/decks and retry scope require readback.
Gap analysis retains the correction from card-quality triage to behavioral
concept-gap hypotheses and excludes marked/flagged cleanup as signals.

## Historical proposal — 2026-10-08 audit

The initial mechanical proposal was a short AGENTS map with no empty state
file, based on the then-unverified durable context. Local input `inventory.json`
contains that discovery snapshot. The authorized source review supersedes its
no-current-state conclusion; it does not authorize code/runtime changes.

## Checks and boundaries

Verify relative routes, source contracts and the README character/privacy
requirements without opening a collection. Keep personal study policy and raw
card data outside this public repository. Runtime readiness, actual card state,
account sync, external schedules and remote delivery need independent evidence
for the particular authorized operational task.


## D-20261010 memory index

Approval: the user approved the memory-index plan on 2026-10-10 (pilot on
`~/.agents`, then one Codex agent per project). Applied: commit `94579c6`. Recovery:
`git revert 94579c6`.

Changed files:

```text
AGENTS.md          |  2 +-
 STATE.md           | 80 ++++++++++++++++++------------------------------------
 docs/operations.md | 11 ++++++++
 3 files changed, 39 insertions(+), 54 deletions(-)
```

Agent receipt:

1. **Line counts:** `STATE.md` **60 → 34**; `AGENTS.md` **23 → 23**. STATE now contains the goal, recorded work status, blockers/questions, six linked decisions and next step.

2. **Moved items:**

| Fact | Destination |
|---|---|
| Runtime-root defaults and public-history privacy | `docs/operations.md` — Queue states and retries |
| Duplicate live `ExternalID` rejection | `docs/operations.md` — Queue states and retries |
| Obsolete backend settings fail | `docs/operations.md` — Select the local owner |
| Upsert checks actual decks and attempts movement | `docs/operations.md` — Verify application and sync separately |

3. **Removed repetition and narration:**

| Removed from STATE | Substance preserved in |
|---|---|
| Headless rationale and retained queue/drain reasons | `docs/decisions/2026-10-01-headless-local-queue.md` |
| Sync, cleanup, deck-verification and gap-analysis explanations | `docs/operations.md` |
| Review date/hash/version and historical correction/event narration | Git history; operative rules remain in topic owners |

4. **New files:** None.

5. **Limits and verification:** No clearly human-authored passage was identified; all substantive rules were retained. `.agents/clean/` audit records could not be updated because that directory is read-only. The excluded `inventory.json` remained untouched.

All **20 relative links and anchors resolve**, and `git diff --check` passes. Only the three documentation files changed; no builds, tests, collection operations or Git mutations were performed.
