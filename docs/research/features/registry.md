# Feature registry

This is the canonical index of candidates and accepted feature definitions.
Do not implement a feature marked only as proposed.

| ID | Family | Feature | Status | Research note | Decision | Output columns |
|---|---|---|---|---|---|---|
| VAL-001 | Valuation | Book-to-market / price-to-book | proposed | — | — | — |
| VAL-002 | Valuation | Earnings yield | proposed | — | — | — |
| VAL-003 | Valuation | Free-cash-flow yield | proposed | — | — | — |
| VAL-004 | Valuation | EV/EBITDA and EBITDA/EV | proposed | — | — | — |
| DST-001 | Distress | Altman-style components | proposed | — | — | — |
| DST-002 | Distress | Ohlson-style components | proposed | — | — | — |
| QLT-001 | Earnings quality | Accruals | proposed | — | — | — |
| QLT-002 | Earnings quality | Beneish-style changes | proposed | — | — | — |
| PRF-001 | Profitability | ROA, ROE, and ROIC | proposed | — | — | — |
| PRF-002 | Profitability | Gross and operating margins | proposed | — | — | — |
| GRW-001 | Growth | Revenue and earnings growth | proposed | — | — | — |
| CAP-001 | Capital allocation | Issuance, repurchase, and dividends | proposed | — | — | — |
| TEC-001 | Technical | Six- and twelve-month total return | proposed | — | — | — |
| TEC-002 | Technical | Volatility and distance from high | proposed | — | — | — |
| SIZ-001 | Size/liquidity | Log market capitalization | proposed | — | — | — |
| SIZ-002 | Size/liquidity | Dollar volume and trading continuity | proposed | — | — | — |
| REG-001 | Market regime | Market return, volatility, and valuation | proposed | — | — | — |

Status transitions:

```text
proposed → researching → review-ready → accepted → implemented
                                  └────→ rejected
```
