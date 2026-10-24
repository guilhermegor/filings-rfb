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

## Recipe: read partners with masked documents

Individuals' CPFs arrive masked by RFB (`***240659**`) and stay that way; never try to unmask
them. Qualification codes are text and join to the `Qualificacoes` lookup.

```python
import pandas as pd

from filings_rfb import read_partners

list_legal_entities = [
    df_chunk[df_chunk["tipo_socio"] == "1"] for df_chunk in read_partners("2026-10")
]
df_legal_entities = pd.concat(list_legal_entities, ignore_index=True)
```

## Recipe: read a CNPJ lookup table

Turn a downloaded lookup ZIP into a typed frame. The `ETag` comes from the share listing and is
stamped on every row, so a stored table says which upstream version produced it.

```python
from pathlib import Path

from filings_rfb import read_lookup


df_cnaes = read_lookup(
    "Cnaes",
    Path("Cnaes.zip"),
    "https://arquivos.receitafederal.gov.br/public.php/dav/files/<token>/2026-10/Cnaes.zip",
    '"17e2f9b2f51164f0e35a0e6011551c63"',
)
print(df_cnaes[["code", "description"]].head())
```
