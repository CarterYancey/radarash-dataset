# V3 — survivorship depth

Status: accepted for M1 (2026-07-13 source snapshot)

The annual artifact counts eligible securities whose TICKERS price interval
contains each calendar year end. The current partial year uses the latest SEP
date. It includes delisted entities and splits them from entities still present
at the source snapshot.

## Results

The filtered universe has 6,025 securities at 1998 year end, 5,620 in 2000,
4,806 in 2002, 4,388 in 2007, 4,213 in 2008, and 4,034 in 2009. Counts of
eligible entities by final-price year are 719 (2000), 673 (2001), 398 (2002),
288 (2008), and 273 (2009).

These counts have a narrower scope than exchange totals: ADRs, secondary
classes, banks, and insurers are excluded. Direction and magnitude are
nevertheless credible. Nasdaq reported 770 issuers ceasing to list in 2001 and
571 in 2002 in its
[2002 Form 10-K](https://www.sec.gov/Archives/edgar/data/1120193/000104746903011291/a2106487z10-k.htm).
Nasdaq reported 289 delistings in 2008 in its
[annual report](https://ir.nasdaq.com/static-files/08c7f365-b412-45b1-a059-77efee69c0d0).
The Sharadar series shows the expected large post-dot-com contraction. Its lack
of a 2008 forced-delisting spike is also plausible because exchange compliance
relief deferred some failures; the universe still contracts through 2009.

## Decision

Use 1998 as the hard floor for M1 and later datasets. Earlier price history
exists, but this verification does not establish comparable survivorship depth
before 1998. Keep 2026 labeled as partial through its explicit as_of_date.
