# Development tasks

This file contains actionable work only. Research notes and theoretical
rationale belong in [PLAN.md](PLAN.md) and `docs/research/`.

## Next: feature research and design

- [ ] Inventory every usable ARQ/ART, DAILY, and SEP source field with units,
      availability date, expected sign/range, and known Sharadar caveats.
- [ ] Create one research note per proposed feature family using the template in
      `docs/research/features/_template.md`.
- [ ] Define the initial feature registry in
      `docs/research/features/registry.md`.
- [ ] Establish denominator, zero, negative-value, winsorization, and infinity
      policies before implementing ratios.
- [ ] Hand-check representative feature calculations against filings and known
      formulas.
- [ ] Decide the first baseline feature set after reviewing evidence and source
      coverage.
- [ ] Record accepted feature definitions in `docs/decisions/`.

## Point-in-time foundation

- [ ] Complete V1: verify about ten ARQ `datekey` values against EDGAR filing
      dates and original reported values.
- [ ] Confirm the first usable trading day is strictly after `datekey`.
- [ ] Implement reusable DuckDB as-of joins from snapshots to ARQ and ART rows.
- [ ] Choose and document the fundamentals staleness cutoff.
- [ ] Add hand-checked off-cycle fiscal-year tests.

## Labels and source verification

- [ ] Complete V4: sample bankruptcies, regulatory delistings, acquisitions, and
      mergers; compare final SEP values with known proceeds or recoveries.
- [ ] Complete V6: verify that SFP SPY `closeadj` represents total return.
- [ ] Measure label flips between terminal-average and point-to-point endpoints.
- [ ] Decide whether terminal-window min/max labels remain in the final dataset.

## Feature implementation

- [ ] Create `src/features/` with a shared point-in-time source layer.
- [ ] Implement accepted families one module at a time with fixture tests.
- [ ] Store each numeric feature as raw value and within-snapshot percentile.
- [ ] Evaluate whether sector-relative ranks add value.
- [ ] Produce null-rate, infinity, outlier, and sector-coverage QA tables.
- [ ] Complete V5 using those QA reports; confirm financial exclusions and REIT
      usability.

## Splits and assembly

- [ ] Read and summarize the required purging, embargo, and CPCV references
      listed in PLAN before writing `src/splits/`.
- [ ] Define per-horizon train/test/purged/embargoed tags.
- [ ] Implement walk-forward folds and final sealed holdout tags.
- [ ] Define and test per-horizon uniqueness weights.
- [ ] Add effective-sample-size QA by era and horizon.
- [ ] Produce immutable `data/datasets/dataset_v1.0.parquet`.
- [ ] Add a single reproducible end-to-end dataset command.

## Operational cleanup

- [ ] Add stage metadata/manifests for interim artifacts.
- [ ] Add schema-version checks between stages.
- [ ] Decide whether generated reports need a lightweight HTML index.
