# Published and learned composite scores

Status: accepted

Production features will be calculated from project point-in-time source data.
Precomputed vendor composites are not a v1 dependency. Vendor values may be
used only as documented spot checks unless historical restatement vintages,
inactive-security coverage, definitions, and identity semantics are proven
compatible.

For Piotroski, Beneish, Ohlson, Zmijewski, Mohanram, and similar methods, the
registry prioritizes meaningful components. An exact published composite may
also be stored as an interpretable reference when all inputs are present, its
original domain is documented, and implementation matches the publication.
Missing components yield a null composite; they are never silently treated as
failed signals or zero.

Dataset v1 will not contain a custom learned quality score. Learned weights,
feature selection, and optimized combinations must be fitted inside temporal
training folds downstream. This avoids baking one model objective into the
dataset and prevents validation/test leakage.
