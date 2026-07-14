# Canonical feature registry

This is the sole canonical registry for feature definitions and review status.
Research lives in [research/features.md](research/features.md); cross-cutting
policy is in ADRs 0004–0006. Do not implement a row until it is `accepted`.

```text
proposed → researched → specified → accepted → implemented
                         └────────→ rejected
```

`specified` means exact source mapping, formula, availability, denominator
policy, applicability, and tests are present. None has reached that stage yet;
source-field and coverage work remains deliberately required.

## V1 registry

| ID | Family | Review unit | Planned outputs | History | Status |
|---|---|---|---|---|---|
| VAL-001 | Valuation | Book and earnings value | book/market, earnings/market | current/TTM | researched |
| VAL-002 | Valuation | Sales and cash-flow value | sales/EV, OCF/EV, FCF/EV | TTM | researched |
| VAL-003 | Valuation | Operating value | EBIT/EV, EBITDA/EV | TTM | researched |
| VAL-004 | Valuation | Shareholder yield | dividend, repurchase, net payout yields | 1y | researched |
| PRF-001 | Profitability | Returns on capital | ROA, guarded ROE, ROIC | TTM | researched |
| PRF-002 | Profitability | Margins | gross, operating, net, cash-flow margins | TTM | researched |
| PRF-003 | Profitability | Gross profitability | gross profit/assets | TTM/current | researched |
| EFF-001 | Efficiency | Turnover | asset and invested-capital turnover | TTM/current | researched |
| QLT-001 | Accruals | Sloan-style accruals | total and working-capital accruals/assets | 1y | researched |
| QLT-002 | Cash conversion | Earnings versus cash flow | OCF/net income and differences | TTM | researched |
| QLT-003 | Manipulation | Beneish components | eight named components | YoY | researched |
| GRW-001 | Growth | Fundamental growth | sales, gross profit, EBIT, earnings, OCF | 1y, selected 3y | researched |
| GRW-002 | Stability | Fundamental stability | slopes, variability, positive-year counts | 3y, selected 5y | researched |
| DST-001 | Solvency | Balance sheet and coverage | leverage, liquidity, working capital, interest coverage | current/TTM | researched |
| DST-002 | Distress | Published-model components | deduplicated Ohlson/Zmijewski/Altman inputs | current, 1y | researched |
| CAP-001 | Investment | Reinvestment intensity | asset growth, capex/assets, R&D/assets | 1y, selected 3y | researched |
| CAP-002 | Financing | Security and debt flows | net equity issuance, net debt issuance | 1y | researched |
| CAP-003 | Distribution | Capital returned | repurchases, dividends, payout coverage | 1y | researched |
| CMP-001 | Reference | Piotroski | continuous inputs, nine flags, exact F-score | current/YoY | researched |
| CMP-002 | Reference | Beneish | exact M-score if complete | YoY | proposed |
| CMP-003 | Reference | Ohlson/Zmijewski | exact legacy scores if reproducible | current/1y | proposed |
| CMP-004 | Reference | Mohanram | components and domain-qualified G-score | multi-year | proposed |
| TEC-001 | Momentum | Trailing return | 1m reversal, 6–1m, 12–1m momentum | daily | researched |
| TEC-002 | Risk/path | Price-path risk | volatility, downside volatility, max drawdown, 52w-high distance | daily 12m | researched |
| LIQ-001 | Size/liquidity | Tradability | log market cap, dollar volume, turnover, continuity | current/daily | researched |
| CTX-001 | Classification | Structural context | sector, industry, calendar/fiscal metadata | current | researched |
| REG-001 | Regime | Broad-market context | market trend, volatility, valuation | varying | proposed |

## Required specification fields

Before moving a review unit to `accepted`, expand it into atomic rows with:

- stable ID and output column name;
- economic direction and expected interpretation;
- exact algebra, units, and period basis;
- source table, dimension, fields, and as-of rule for every input;
- required lookback and staleness rule;
- zero/negative denominator, null, and infinity policy;
- sector/business-model applicability;
- raw/rank output policy;
- fixture cases and full-data QA checks;
- evidence and an ADR for material conventions;
- definition version and compatibility notes.

Shared inputs must be canonicalized, not reimplemented per composite. If a
publication requires a materially different definition, give that input a
clear, separate name.
