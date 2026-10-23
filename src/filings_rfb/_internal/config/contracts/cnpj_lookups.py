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


CNAES = FileContract("CNPJ Cnaes", "cnpj_cnaes", ("code", "description"), (), True)
MOTIVOS = FileContract("CNPJ Motivos", "cnpj_motivos", ("code", "description"), (), True)
MUNICIPIOS = FileContract("CNPJ Municipios", "cnpj_municipios", ("code", "description"), (), True)
NATUREZAS = FileContract("CNPJ Naturezas", "cnpj_naturezas", ("code", "description"), (), True)
PAISES = FileContract("CNPJ Paises", "cnpj_paises", ("code", "description"), (), True)
QUALIFICACOES = FileContract(
    "CNPJ Qualificacoes", "cnpj_qualificacoes", ("code", "description"), (), True
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
