"""Data contract for the RFB CNPJ ``Simples`` file (``Simples.zip``).

The source is headerless: the seven columns below are the published layout, in order.
``cnpj_basico`` is the 8-digit CNPJ root, so it is deliberately **not** listed in
``tuple_cnpj_cols`` (the CNPJ validator expects the full 14 characters).
"""

from __future__ import annotations

from filings_rfb._internal.utils.tabular_reader import FileContract


COLUMNS_SIMPLES: tuple[str, ...] = (
    "cnpj_basico",
    "opcao_pelo_simples",
    "data_opcao_simples",
    "data_exclusao_simples",
    "opcao_pelo_mei",
    "data_opcao_mei",
    "data_exclusao_mei",
)

CNPJ_SIMPLES = FileContract("Simples", "cnpj_simples", COLUMNS_SIMPLES, (), True)
