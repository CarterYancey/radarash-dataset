# Feature research workspace

This directory is the working memory for feature development. It may be
detailed; README and AGENTS should only link here.

## Structure

- `registry.md`: canonical index and review status for every candidate.
- `_template.md`: required sections for a feature or family note.
- one Markdown file per family, such as `valuation.md`,
  `earnings-quality.md`, or `technical.md`.
- optional generated Parquet or image outputs belong under ignored
  `data/interim/qa/features/`; notes link to them but do not embed raw data.

## Workflow

1. Add a candidate to the registry as proposed.
2. Research it using the template.
3. Prototype formulas and produce coverage/distribution evidence.
4. Mark it review-ready and link the note.
5. If accepted, lock material conventions in a decision record.
6. Implement it with fixture tests and update the registry status.

The registry is not a task tracker. Implementation tasks stay in TODO.
