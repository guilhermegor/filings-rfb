# **filings-rfb** <img src="assets/logo.png" align="right" width="200" style="border-radius: 15px;" alt="filings-rfb">

Typed pandas readers for the Receita Federal do Brasil (RFB) CNPJ open data: Empresas, Estabelecimentos, Socios, Simples and the six lookup tables, read as memory-flat chunks.

*Unofficial, community library. Not affiliated with or endorsed by the Receita Federal do Brasil; the emblem belongs to that agency.*

---

## Contents

| Section | Description |
|---------|-------------|
| [Usage](usage.md) | Installation, imports, and usage examples |
| [Examples](examples.md) | Task-oriented recipes per reader |
| [API Reference](api/index.md) | Module-level functions and public interface |
| [FAQ](faq.md) | Common questions |

---

## Quick start

```bash
pip install filings-rfb
```

```python
from filings_rfb import read_companies

for df_chunk in read_companies("2026-10"):
    ...
```

The RFB publishes one folder per month. `Estabelecimentos` (up to 2.3 GB per compressed part) and
`Simples` (~3.2 GB inflated) are large: the readers stream them to disk and yield chunks.
