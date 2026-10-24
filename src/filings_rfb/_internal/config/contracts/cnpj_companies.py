"""Data contract for the RFB CNPJ ``Empresas`` files (``Empresas0.zip`` .. ``Empresas9.zip``).

The source is headerless: the seven columns below are the published layout, in order, and the
reader assigns them by position. ``cnpj_basico`` is the 8-digit CNPJ root, so it is deliberately
**not** listed in ``tuple_cnpj_cols`` (the CNPJ validator expects the full 14 characters).
"""

from __future__ import annotations

from filings_rfb._internal.utils.tabular_reader import FileContract


COLUMNS_COMPANIES: tuple[str, ...] = (
    "cnpj_basico",
    "razao_social",
    "natureza_juridica",
    "qualificacao_responsavel",
    "capital_social",
    "porte_empresa",
    "ente_federativo_responsavel",
)

CNPJ_COMPANIES = FileContract("Empresas", "cnpj_companies", COLUMNS_COMPANIES, (), True)
