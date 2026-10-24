"""Data contracts for the project's input files (config layer).

A contract is **declarative configuration** of an input's expected shape — which columns a
source must carry, which must hold valid CNPJs — *not* data access, so contracts live in
``config`` beside the other declarative config (``inputs.yaml``, ``connection_db``), imported
by the model loaders and the controller boundary.

Convention: **one file per source** under this package (``cadastro.py``, ``orders.py``, …),
each defining a single ``FileContract`` instance; this aggregator re-exports them (plus the
machinery from ``utils.tabular_reader``) so callers import from one place:
``from config.contracts import EXAMPLE_SOURCE, find_file_problems``.

``EXAMPLE_SOURCE`` is a reference instance — copy ``example_source.py`` per real source and
delete the example once your own contracts exist.
"""

from __future__ import annotations

from filings_rfb._internal.config.contracts.cnpj_companies import (
    CNPJ_COMPANIES,
    COLUMNS_COMPANIES,
)
from filings_rfb._internal.config.contracts.cnpj_lookups import (
    CNAES,
    CNPJ_LOOKUP_CONTRACTS,
    CNPJ_LOOKUP_NAMES,
    MOTIVOS,
    MUNICIPIOS,
    NATUREZAS,
    PAISES,
    QUALIFICACOES,
)
from filings_rfb._internal.config.contracts.example_source import EXAMPLE_SOURCE
from filings_rfb._internal.utils.tabular_reader import (
    ContractError,
    FileContract,
    find_file_problems,
)


__all__ = [
    "CNAES",
    "CNPJ_COMPANIES",
    "CNPJ_LOOKUP_CONTRACTS",
    "CNPJ_LOOKUP_NAMES",
    "COLUMNS_COMPANIES",
    "EXAMPLE_SOURCE",
    "MOTIVOS",
    "MUNICIPIOS",
    "NATUREZAS",
    "PAISES",
    "QUALIFICACOES",
    "ContractError",
    "FileContract",
    "find_file_problems",
]
