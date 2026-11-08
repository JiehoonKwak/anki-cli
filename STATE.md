# Anki CLI state

## Backfill existing concept cards to the mobile visual style (not started)

The user wants every existing non-vocabulary card rewritten to the current
`anki` skill's concept-card style (core answer first, one visual chosen for
that card, short back, night-mode-safe colors, no paper-figure crops), later,
when they ask for it.

- Scope: all notes outside the `Vocabulary` deck and not tagged as vocabulary,
  including old `Basic`/Obsidian imports. Vocabulary is excluded.
- Change content fields only (`Front`, `Back`, `Extra` and media). Keep note
  and card IDs, deck, tags, flags and all scheduling/review history: update
  fields in place (`client.update_note` or an upsert with the same
  `ExternalID`), never delete and re-add. Compare each card's type, queue,
  due, interval, reps and lapses before and after.
- The skill's draft-first rule still applies: show batches as a phone-width
  preview for approval before writing.
- Card contents stay out of this repository; keep drafts and progress in the
  private runtime directory.
