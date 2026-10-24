"""Data contract for the RFB CNPJ ``Estabelecimentos`` files (``Estabelecimentos0..9.zip``).

The source is headerless: the 30 columns below are the published layout, in order, and the
reader assigns them by position. The CNPJ is split across ``cnpj_basico`` (8), ``cnpj_ordem``
(4) and ``cnpj_dv`` (2), so none of them is listed in ``tuple_cnpj_cols`` (the validator expects
the full 14 characters); the reader derives and validates ``cnpj_completo`` itself.
"""

from __future__ import annotations

from filings_rfb._internal.utils.tabular_reader import FileContract


COLUMNS_ESTABLISHMENTS: tuple[str, ...] = (
    "cnpj_basico",
    "cnpj_ordem",
    "cnpj_dv",
    "identificador_matriz_filial",
    "nome_fantasia",
    "situacao_cadastral",
    "data_situacao_cadastral",
    "motivo_situacao_cadastral",
    "nome_cidade_exterior",
    "pais",
    "data_inicio_atividade",
    "cnae_fiscal_principal",
    "cnae_fiscal_secundaria",
    "tipo_logradouro",
    "logradouro",
    "numero",
    "complemento",
    "bairro",
    "cep",
    "uf",
    "municipio",
    "ddd_1",
    "telefone_1",
    "ddd_2",
    "telefone_2",
    "ddd_fax",
    "fax",
    "correio_eletronico",
    "situacao_especial",
    "data_situacao_especial",
)

CNPJ_ESTABLISHMENTS = FileContract(
    "Estabelecimentos", "cnpj_establishments", COLUMNS_ESTABLISHMENTS, (), True
)
