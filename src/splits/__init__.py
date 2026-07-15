"""Purged/embargoed split tagging (M5, PLAN.md §7, decision 0010).

Tags every (snapshot, horizon) row with a role per (scheme, fold) —
train / test / purged / embargoed — instead of filtering anything: splits
are tags, never filters, so no labels row is ever dropped (survivorship
invariant). `folds` derives the fold calendar from the labels table and
freezes it into a manifest; `tags` assigns roles against that calendar.
"""
