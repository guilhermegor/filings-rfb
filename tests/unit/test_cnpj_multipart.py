"""Unit tests for the shared multi-part chunked reader (no network, tiny fake ZIPs)."""

from __future__ import annotations

from collections.abc import Callable
import contextlib
from email.message import Message
from http.client import HTTPResponse
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock
from urllib import error
from urllib.request import Request

import pandas as pd
import pytest

from filings_rfb._internal.config.contracts import CNPJ_COMPANIES, ContractError
from filings_rfb._internal.utils import stream_downloader
from filings_rfb._internal.utils.stream_downloader import download_file_streaming
from filings_rfb.ingestion.cnpj import _multipart
from filings_rfb.ingestion.cnpj._multipart import iter_part_chunks
from tests.unit.conftest import LIST_PART0_LINES, LIST_PART1_LINES, STR_MONTH


DICT_DTYPES = {str_col: "str" for str_col in CNPJ_COMPANIES.tuple_required}
Publish = Callable[[dict[int, list[str]]], MagicMock]


def _read(int_chunk_rows: int, tuple_parts: tuple[int, ...] = (0, 1)) -> list[pd.DataFrame]:
    """Drain the iterator over the given parts.

    Parameters
    ----------
    int_chunk_rows : int
        Rows per chunk.
    tuple_parts : tuple of int, optional
        The parts to read.

    Returns
    -------
    list of pd.DataFrame
        Every chunk.
    """
    return list(
        iter_part_chunks(
            STR_MONTH,
            "Empresas",
            CNPJ_COMPANIES,
            DICT_DTYPES,
            int_chunk_rows=int_chunk_rows,
            tuple_parts=tuple_parts,
        )
    )


def test_chunks_split_at_the_requested_row_count(fake_share: Publish) -> None:
    """Part 0 has three rows: chunks of two give 2 + 1, then part 1 gives 1."""
    fake_share({0: LIST_PART0_LINES, 1: LIST_PART1_LINES})
    assert [len(df_chunk) for df_chunk in _read(2)] == [2, 1, 1]


def test_part_index_and_etag_are_stamped_per_part(fake_share: Publish) -> None:
    """Every row carries the part it came from and that archive's ETag."""
    fake_share({0: LIST_PART0_LINES, 1: LIST_PART1_LINES})
    df_all = pd.concat(_read(2), ignore_index=True)
    assert df_all[["part_index", "source_etag"]].drop_duplicates().to_numpy().tolist() == [
        [0, '"etag-Empresas0.zip"'],
        [1, '"etag-Empresas1.zip"'],
    ]


def test_all_chunks_of_one_read_share_one_run_id(fake_share: Publish) -> None:
    """The ingestion run id is minted once per read, not per chunk."""
    fake_share({0: LIST_PART0_LINES, 1: LIST_PART1_LINES})
    assert len(set(pd.concat(_read(2))["ingestion_run_id"])) == 1


def test_latin1_accents_round_trip(fake_share: Publish) -> None:
    """A latin-1 accented name is decoded, not mangled."""
    fake_share({0: LIST_PART0_LINES, 1: LIST_PART1_LINES})
    assert "CONSTRUÇÕES JOÃO LTDA" in pd.concat(_read(2))["razao_social"].tolist()


def test_missing_part_raises_instead_of_skipping(fake_share: Publish) -> None:
    """Asking for part 1 when only part 0 is published is an error."""
    fake_share({0: LIST_PART0_LINES})
    with pytest.raises(FileNotFoundError, match="Empresas1.zip"):
        _read(2)


def test_missing_part_downloads_nothing(fake_share: Publish) -> None:
    """The completeness check runs before any download starts."""
    mock_download = fake_share({0: LIST_PART0_LINES})
    with contextlib.suppress(FileNotFoundError):
        _read(2)
    assert mock_download.call_count == 0


def test_non_positive_chunk_size_is_rejected(fake_share: Publish) -> None:
    """A zero chunk size fails fast instead of reading everything at once."""
    fake_share({0: LIST_PART0_LINES, 1: LIST_PART1_LINES})
    with pytest.raises(ValueError, match="int_chunk_rows"):
        _read(0)


def test_wrong_column_count_raises_contract_error(fake_share: Publish) -> None:
    """A part with an extra field is rejected, never silently re-indexed."""
    fake_share({0: ['"1";"A";"2";"3";"4,00";"5";"";"EXTRA"']})
    with pytest.raises(ContractError, match="expected 7"):
        _read(2, (0,))


def test_temporary_workdir_is_cleaned_after_the_read(fake_share: Publish) -> None:
    """Without a workdir the downloaded archive does not outlive the read."""
    mock_download = fake_share({0: LIST_PART0_LINES, 1: LIST_PART1_LINES})
    _read(2)
    assert not mock_download.call_args.args[1].exists()


def test_module_exposes_ten_default_parts() -> None:
    """The default part set is 0 through 9."""
    assert tuple(range(10)) == _multipart.DEFAULT_PARTS


def _read_workdir(path_workdir: Path) -> None:
    """Drain a two-part read that keeps its ZIPs in ``path_workdir``.

    Parameters
    ----------
    path_workdir : pathlib.Path
        The directory the ZIPs are kept in.
    """
    list(
        iter_part_chunks(
            STR_MONTH,
            "Empresas",
            CNPJ_COMPANIES,
            DICT_DTYPES,
            path_workdir=path_workdir,
            tuple_parts=(0, 1),
        )
    )


class _FakeResponse(HTTPResponse):
    """A 200 response with a fixed body, standing in for the share."""

    def __init__(self, bytes_body: bytes, str_etag: str) -> None:
        self.fp = None
        self.status = 200
        self.headers = Message()
        self.headers["ETag"] = str_etag
        self.headers["Content-Length"] = str(len(bytes_body))
        self._cls_buffer = BytesIO(bytes_body)

    def read(self, amt: int | None = None) -> bytes:
        """Read from the in-memory body.

        Parameters
        ----------
        amt : int or None
            Maximum bytes to read.

        Returns
        -------
        bytes
            The next slice of the body.
        """
        return self._cls_buffer.read(amt)


class _FakeOrigin:
    """Opener that answers 304 to a matching ``If-None-Match`` and counts the bodies served."""

    def __init__(self, dict_bodies: dict[str, bytes]) -> None:
        self.dict_bodies = dict_bodies
        self.int_bodies_served = 0

    def open(  # noqa: A003  # complexity-ok: stub server protocol (304 vs 200)
        self, cls_request: Request, timeout: int
    ) -> _FakeResponse:
        """Serve the part named by the URL, or a 304 when the ETag is current.

        Parameters
        ----------
        cls_request : urllib.request.Request
            The request.
        timeout : int
            Ignored.

        Returns
        -------
        _FakeResponse
            The 200 response.

        Raises
        ------
        urllib.error.HTTPError
            A 304 when ``If-None-Match`` matches.
        """
        str_name = cls_request.full_url.rsplit("/", 1)[-1]
        str_etag = f'"etag-{str_name}"'
        if cls_request.get_header("If-none-match") == str_etag:
            raise error.HTTPError(cls_request.full_url, 304, "Not Modified", Message(), None)
        self.int_bodies_served += 1
        return _FakeResponse(self.dict_bodies[str_name], str_etag)


def test_rerun_with_workdir_serves_no_body_the_second_time(
    fake_share: Publish, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second read over the same workdir revalidates each ZIP (304) and reads no body.

    Parameters
    ----------
    fake_share : Publish
        Registers the fake published parts.
    tmp_path : pathlib.Path
        pytest fixture.
    monkeypatch : pytest.MonkeyPatch
        pytest fixture.
    """
    fake_share({0: LIST_PART0_LINES, 1: LIST_PART1_LINES})
    dict_bodies = {
        f"Empresas{int_part}.zip": (tmp_path / f"src_{int_part}.zip").read_bytes()
        for int_part in (0, 1)
    }
    cls_origin = _FakeOrigin(dict_bodies)
    monkeypatch.setattr(_multipart, "download_file_streaming", download_file_streaming)
    monkeypatch.setattr(stream_downloader, "_OPENER", cls_origin)
    monkeypatch.setattr(stream_downloader, "_assert_url_allowed", lambda _str_url: None)
    _read_workdir(tmp_path / "work")
    _read_workdir(tmp_path / "work")
    assert cls_origin.int_bodies_served == 2
