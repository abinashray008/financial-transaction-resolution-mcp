# Synthetic dataset

All data is invented for this project. Nothing is scraped or licensed from a
financial institution.

| | |
| --- | --- |
| **Name** | Synthetic card-transaction dataset |
| **Source** | Generated in-repo by `src/app/data_seed.py` via `scripts/generate_data.py` |
| **Storage** | `data/transactions.db` (SQLite; gitignored) |
| **Checkpoints** | Paused LangGraph review threads are stored separately in `data/checkpoints.db` (also gitignored) |
| **Format** | See [data-model.md](data-model.md) |
| **Preprocessing** | None. Tables are dropped and recreated on each run. Dates are anchored to a fixed reference date (`2026-06-30`), so the dataset does not drift. |
| **License** | Original synthetic content under this repository's MIT license. Names, merchants and descriptors correspond to no real person or business. |

Regenerate:

```bash
uv run python scripts/generate_data.py --seed 42
```

A given seed always produces the same logical dataset. Running the generator
again does not duplicate rows.

## Volumes at seed 42

- 100 customers
- 150 accounts
- 75 merchants
- 5,000 background transactions
- ~150 interesting transactions (`TXN-INT-*`)
- 12 hand-written scenario rows on the demo accounts

`ACCT-0001` is the scenario account. Background generation never reuses the
scenario merchants on it.

## Demo scenarios

| Scenario | Transactions |
| --- | --- |
| Exact duplicate charge | `TXN-SCN-DUP-A`, `TXN-SCN-DUP-B` on `ACCT-0001` |
| Recurring subscription | `TXN-SCN-SUB-01/02/03` |
| Descriptor ≠ display name | `TXN-SCN-DESC-01` (`SQ *RVRBND COFFEE…` → Riverbend Coffee Roasters) |
| Hotel authorization hold | `TXN-SCN-HOLD-01` (hold) and `TXN-SCN-HOLD-02` (posted) |
| Foreign transaction | `TXN-SCN-FX-01` — 64.20 EUR in France |
| Posted / pending | `TXN-SCN-POSTED-01`, `TXN-SCN-PENDING-01` |
| Same charge, other account | `TXN-SCN-OTHER-01` on `ACCT-0002` (isolation tests) |

The hotel pair returns **LOW** duplicate confidence: an authorization hold
paired with a posted charge is normal settlement. Monthly subscriptions are
downgraded the same way. Example queries for these scenarios are in
[demo-guide.md](demo-guide.md).
