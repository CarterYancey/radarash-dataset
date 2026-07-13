"""Forward-return label construction (M3, README §6).

Two-stage design so triple-barrier labels can be added later without
rewrites: `paths` extracts forward daily adjusted-price paths (all delisting
handling lives there and only there); `compute` holds the label functions,
which are pure aggregations over those paths.
"""
