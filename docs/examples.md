# **Examples**

Task-oriented, self-contained snippets for common uses of this library. Each recipe stands
alone — copy it and adjust.

> **See also:** [Usage](usage.md) for the basics · [API Reference](api/index.md) for every public
> symbol.

---

## Recipe: iterate Empresas without loading it all

Each chunk is a typed frame, so aggregate as you go and keep memory flat.

```python
from decimal import Decimal

from filings_rfb import read_companies

decimal_total = Decimal(0)
for df_chunk in read_companies("2026-10"):
    decimal_total += sum(df_chunk["capital_social"].dropna(), Decimal(0))
print(decimal_total)
```

## Recipe: export to Parquet and query it with DuckDB

Reading the ZIPs always decompresses everything once; lazy querying only pays off afterwards,
against a columnar file. Export once, then let DuckDB (installed on your side, not a dependency of
this library) scan it.

```python
from pathlib import Path

import duckdb

from filings_rfb import export_companies_parquet

path_parquet = export_companies_parquet("2026-10", Path("empresas_2026-10.parquet"))
print(
    duckdb.sql(
        f"SELECT razao_social, capital_social FROM '{path_parquet}' "
        "ORDER BY capital_social DESC LIMIT 5"
    )
)
```
