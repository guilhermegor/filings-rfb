"""Unit tests for the six CNPJ lookup-table readers (offline, trimmed real fixtures)."""

import hashlib
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from filings_rfb._internal.config.contracts import (
    CNPJ_LOOKUP_CONTRACTS,
    CNPJ_LOOKUP_NAMES,
    ContractError,
)
from filings_rfb._internal.utils.provenance import hash_artifact
from filings_rfb.ingestion.cnpj.lookups import read_lookup


PATH_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cnpj"
STR_URL = "https://example.invalid/2026-10/{}.zip"
STR_ETAG = '"17e2f9b2f51164f0e35a0e6011551c63"'
STR_SHA256_QUALIFICACOES = "47660f33c6d19ba1a56a8aaceb9db42eac2a96284b65597dd3821709f5fedd3c"


def _read(str_table: str) -> pd.DataFrame:
    """Read one trimmed real fixture through the public reader.

    Parameters
    ----------
    str_table : str
        The lookup table name, e.g. ``"Cnaes"``.

    Returns
    -------
    pd.DataFrame
        The stamped frame.
    """
    return read_lookup(
        str_table,
        PATH_FIXTURES / f"lookup_{str_table.lower()}.zip",
        STR_URL.format(str_table),
        STR_ETAG,
    )


def _write_zip(path_zip: Path, dict_members: dict[str, bytes]) -> Path:
    """Write a throwaway archive holding ``dict_members``.

    Parameters
    ----------
    path_zip : pathlib.Path
        Where to write the archive.
    dict_members : dict of {str: bytes}
        Member name to content.

    Returns
    -------
    pathlib.Path
        ``path_zip``.
    """
    with zipfile.ZipFile(path_zip, "w") as cls_zip:
        for str_name, bytes_content in dict_members.items():
            cls_zip.writestr(str_name, bytes_content)
    return path_zip


@pytest.mark.parametrize("str_table", CNPJ_LOOKUP_NAMES)
def test_read_lookup_each_table_returns_code_and_description_plus_provenance(
    str_table: str,
) -> None:
    """Every table yields ``code``/``description`` then the provenance columns."""
    df_out = _read(str_table)
    assert tuple(df_out.columns) == CNPJ_LOOKUP_CONTRACTS[str_table].output_columns + (
        "source_etag",
    )


def test_lookup_names_are_the_six_published_tables() -> None:
    """The registry names exactly the six RFB lookup files."""
    assert set(CNPJ_LOOKUP_NAMES) == {
        "Cnaes",
        "Motivos",
        "Municipios",
        "Naturezas",
        "Paises",
        "Qualificacoes",
    }


def test_read_lookup_keeps_leading_zeros_as_strings() -> None:
    """A zero-padded code must not be coerced to a number."""
    df_out = _read("Municipios")
    assert df_out["code"].tolist() == ["0001", "0002", "0003"]


def test_read_lookup_decodes_latin1_accents() -> None:
    """Accented ``latin-1`` descriptions survive intact (no mojibake)."""
    df_out = _read("Naturezas")
    assert "Natureza Jurídica não informada" in df_out["description"].tolist()


def test_read_lookup_text_columns_are_nullable_string_dtype() -> None:
    """Columns are typed explicitly, never left to pandas' inference."""
    df_out = _read("Cnaes")
    assert (str(df_out["code"].dtype), str(df_out["description"].dtype)) == ("string", "string")


def test_read_lookup_stamps_source_url_etag_and_content_hash() -> None:
    """Provenance carries the URL, the source ETag and the archive's sha256."""
    path_zip = PATH_FIXTURES / "lookup_paises.zip"
    df_out = _read("Paises")
    assert (
        df_out["url"].iloc[0],
        df_out["source_etag"].iloc[0],
        df_out["content_hash"].iloc[0],
    ) == (STR_URL.format("Paises"), STR_ETAG, hash_artifact(path_zip))


def test_read_lookup_stamps_source_key_per_table() -> None:
    """The ``source_key`` tells the six tables apart in a shared bronze layer."""
    assert _read("Motivos")["source_key"].iloc[0] == "cnpj_motivos"


def test_read_lookup_round_trips_to_the_pinned_member_digest() -> None:
    """Anti-tautology: re-serialising the frame reproduces a digest nobody typed in.

    The digest was generated from the committed member bytes, so a reader that silently
    changes encoding, quoting or row content cannot agree with itself and still pass.
    """
    df_out = _read("Qualificacoes")
    str_csv = "".join(
        f'"{str_code}";"{str_desc}"\n'
        for str_code, str_desc in zip(df_out["code"], df_out["description"], strict=True)
    )
    assert hashlib.sha256(str_csv.encode("latin-1")).hexdigest() == STR_SHA256_QUALIFICACOES


def test_read_lookup_picks_the_member_whatever_its_name(tmp_path: Path) -> None:
    """A member not ending in ``.csv`` is still read (the stpstone empty-frame bug)."""
    path_zip = _write_zip(tmp_path / "x.zip", {"ANYTHING.NOTCSV": b'"1";"a"\n'})
    df_out = read_lookup("Motivos", path_zip, "https://example.invalid/x.zip", STR_ETAG)
    assert df_out["code"].tolist() == ["1"]


def test_read_lookup_zero_members_raises(tmp_path: Path) -> None:
    """An archive with no file member fails loudly."""
    path_zip = _write_zip(tmp_path / "empty.zip", {})
    with pytest.raises(ValueError, match="exactly one"):
        read_lookup("Motivos", path_zip, "https://example.invalid/x.zip", STR_ETAG)


def test_read_lookup_several_members_raises(tmp_path: Path) -> None:
    """An archive with several file members is ambiguous, never guessed."""
    path_zip = _write_zip(tmp_path / "two.zip", {"A": b'"1";"a"\n', "B": b'"2";"b"\n'})
    with pytest.raises(ValueError, match="exactly one"):
        read_lookup("Motivos", path_zip, "https://example.invalid/x.zip", STR_ETAG)


def test_read_lookup_unknown_table_raises(tmp_path: Path) -> None:
    """An unknown table name is rejected before the archive is opened."""
    with pytest.raises(ValueError, match="Unknown lookup table"):
        read_lookup("Empresas", tmp_path / "nope.zip", "https://example.invalid/x.zip", STR_ETAG)


def test_read_lookup_wrong_column_count_raises_contract_error(tmp_path: Path) -> None:
    """A three-column member is not the published ``code;description`` shape."""
    path_zip = _write_zip(tmp_path / "wide.zip", {"M": b'"1";"a";"extra"\n'})
    with pytest.raises(ContractError, match="two columns"):
        read_lookup("Motivos", path_zip, "https://example.invalid/x.zip", STR_ETAG)
