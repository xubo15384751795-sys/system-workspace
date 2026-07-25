# Wardley map — build only where evolution has not already won

```mermaid
flowchart LR
  Genesis["Genesis<br/>judgment machine<br/>agent constitution<br/>judgment ledger<br/>X stock model"]
  Custom["Custom<br/>thin pipeline glue<br/>measurement adapters<br/>bridge and admission wiring"]
  Product["Product<br/>DuckDB<br/>statsmodels<br/>hmmlearn<br/>package runtimes"]
  Commodity["Commodity<br/>public stress indices<br/>FRED<br/>momentum and volatility targets<br/>backtest engines"]
  Genesis --> Custom --> Product --> Commodity
```

Evolution runs left to right. Investment runs left: concentrate design effort
on judgment, constitutional boundaries, ledgers and genuinely new state models.
Keep adapters thin. Use products as libraries. Consume commodities through
replaceable providers; never rebuild them.

The build rule is one sentence: before deciding to build X, place X on this
map; if it is in Product or Commodity, do not build it. Record the placement in
the routing decision for any non-trivial build.

Redraw quarterly. A component moving right is a deletion or replacement signal,
not a reason to defend sunk cost. Measurement is presumed to drift right unless
evidence shows that its semantics remain system-specific.
