"""Data contracts for the six RFB CNPJ lookup tables.

Each table is published as one headerless, ``;``-separated, fully quoted ``latin-1`` CSV of two
columns, ``code;description``, so the six contracts differ only in name and source key. They
are declared here (never built in the reader) and every one is full-column: the header is
supplied by the reader, so the two columns *are* the complete published shape.

``Qualificacoes`` is the partner/representative **qualification** (role); the legacy stpstone
module mislabelled it "shareholders education".
"""

from __future__ import annotations

from filings_rfb._internal.utils.tabular_reader import FileContract


_COLUMNS = ("code", "description")
_STAMPED = ("source_etag",)

CNAES = FileContract("CNPJ Cnaes", "cnpj_cnaes", _COLUMNS, (), True, _STAMPED)
MOTIVOS = FileContract("CNPJ Motivos", "cnpj_motivos", _COLUMNS, (), True, _STAMPED)
MUNICIPIOS = FileContract("CNPJ Municipios", "cnpj_municipios", _COLUMNS, (), True, _STAMPED)
NATUREZAS = FileContract("CNPJ Naturezas", "cnpj_naturezas", _COLUMNS, (), True, _STAMPED)
PAISES = FileContract("CNPJ Paises", "cnpj_paises", _COLUMNS, (), True, _STAMPED)
QUALIFICACOES = FileContract(
    "CNPJ Qualificacoes", "cnpj_qualificacoes", _COLUMNS, (), True, _STAMPED
)

CNPJ_LOOKUP_CONTRACTS: dict[str, FileContract] = {
    "Cnaes": CNAES,
    "Motivos": MOTIVOS,
    "Municipios": MUNICIPIOS,
    "Naturezas": NATUREZAS,
    "Paises": PAISES,
    "Qualificacoes": QUALIFICACOES,
}
CNPJ_LOOKUP_NAMES: tuple[str, ...] = tuple(CNPJ_LOOKUP_CONTRACTS)
