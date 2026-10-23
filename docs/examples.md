# **Examples**

Task-oriented, self-contained snippets for common uses of this library. Each recipe stands
alone — copy it and adjust.

> **See also:** [Usage](usage.md) for the basics · [API Reference](api/index.md) for every public
> symbol.

---

## Recipe: <a common task>

Briefly describe the problem this recipe solves, then show the smallest working snippet.

```python
from <project_name> import main


# Replace with a real, runnable example of your public API.
main()
```

## Recipe: <another task>

Add one `##` section per recipe. Comments in the code should explain **why**, not just what.

```python
# Replace with a second illustrative example.
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
