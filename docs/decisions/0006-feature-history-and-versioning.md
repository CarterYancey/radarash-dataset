# Feature history and independent versioning

Status: accepted

All label horizons use the same point-in-time feature row. Feature definitions
do not change implicitly for 1-, 2-, 3-, or 5-year labels. Downstream models
may select different subsets by horizon.

History follows economic meaning: current/TTM and one-year comparisons are
baseline; three-year trend/stability and five-year durability are selective;
published formulas retain specified windows. Insufficient history produces
null values and coverage metadata, not removal of a snapshot or universe member.

Backward-looking history does not extend purge or embargo boundaries because
it is known at the snapshot. Forward label overlap determines those boundaries.
Pre-split observations may support a feature when every input was public before
the snapshot. Imputation, scaling, selection, and learned combinations are fit
only inside training folds.

Features and labels are independently versioned artifacts joined to the stable
snapshot spine. A dataset composes explicit snapshot, universe, feature-set,
label-set, and split specifications. Changing one component must not require
recomputing unrelated components.
