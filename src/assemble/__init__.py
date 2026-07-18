"""Dataset assembly (M5): families × labels × splits → data/datasets/.

The final stage of the pipeline. Joins the per-family feature parquets to
`labels.parquet` on the shared snapshot key (validating each family's
columns against the registry), computes the registry-driven rank and
sector-rank columns (decision 0008), the two assembly-stage composites
`mohanram_g7` and `conservative_score` (decision 0013), and the per-horizon
uniqueness weights `sample_weight_{H}y` (decision 0012), then writes a
versioned, immutable dataset directory
`data/datasets/dataset_vX.Y/` containing `dataset.parquet`, the split tags
copied verbatim (`splits.parquet`, `split_folds.parquet`), and a
`manifest.json` provenance record. Canonical column definitions:
docs/dataset.md.
"""
