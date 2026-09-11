# Excel / VBA Implementation

## File

`fulcrum_pnl.xlsm` — macro-enabled workbook.

## Sheets

| Sheet | Purpose |
|-------|---------|
| RawData | Imported bank-additional-full.csv |
| Dashboard | Pivot tables + charts for campaign KPIs |
| P&L | Unit-economics model with scenario toggles |
| VBA_Log | Macro execution log |

## VBA Modules

- `mod_Import` — Refreshes data from CSV.
- `mod_PnL` — Recalculates P&L under user-defined cost/revenue assumptions.
