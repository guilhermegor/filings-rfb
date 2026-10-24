"""Data contract for the RFB CNPJ ``Socios`` files (``Socios0.zip`` .. ``Socios9.zip``).

The source is headerless: the eleven columns below are the published layout, in order.
``qualificacao_*`` are codes that join to the ``Qualificacoes`` lookup (legacy readers called
them "education"). ``documento_socio`` mixes a full CNPJ (legal entity) with a pre-masked CPF
(``***dddddd**``) so it is deliberately **not** in ``tuple_cnpj_cols``: the CNPJ validator
would reject every masked individual.
"""

from __future__ import annotations

from filings_rfb._internal.utils.tabular_reader import FileContract


COLUMNS_PARTNERS: tuple[str, ...] = (
    "cnpj_basico",
    "tipo_socio",
    "nome_socio",
    "documento_socio",
    "qualificacao_socio",
    "data_entrada",
    "pais",
    "documento_representante",
    "nome_representante",
    "qualificacao_representante",
    "faixa_etaria",
)

CNPJ_PARTNERS = FileContract("Socios", "cnpj_partners", COLUMNS_PARTNERS, (), True)
