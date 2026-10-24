"""Shared fixtures for the multi-part CNPJ reader tests: a fake share of tiny Empresas ZIPs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import zipfile

import pytest

from filings_rfb._internal.utils.webdav_client import WebdavEntry
from filings_rfb.ingestion.cnpj import _multipart


STR_MONTH = "2026-10"
LIST_PART0_LINES = [
    '"00000000";"BANCO DO BRASIL SA";"2038";"10";"120000000000,00";"05";""',
    '"00000001";"CONSTRUÇÕES JOÃO LTDA";"2062";"49";"1234,50";"01";""',
    '"00000002";"TRES";"2062";"49";"0,00";"01";""',
]
LIST_PART1_LINES = ['"00000003";"QUATRO";"2062";"49";"7,07";"03";"SP"']


def _write_part_zip(path_zip: Path, list_lines: list[str]) -> None:
    """Write a ZIP whose single member is the latin-1 encoded CSV of ``list_lines``.

    Parameters
    ----------
    path_zip : pathlib.Path
        The ZIP to create.
    list_lines : list of str
        The CSV rows.
    """
    with zipfile.ZipFile(path_zip, "w", zipfile.ZIP_DEFLATED) as cls_zip:
        cls_zip.writestr("K3241.K03200Y0.D61010.EMPRECSV", "\n".join(list_lines).encode("latin-1"))


@pytest.fixture
def fake_share(  # complexity-ok: fixture factory with a nested fake
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Callable[[dict[int, list[str]]], MagicMock]:
    """Patch the catalogue and the downloader so parts come from tiny local ZIPs.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        pytest fixture.
    tmp_path : pathlib.Path
        pytest fixture; the fake archives live here.

    Returns
    -------
    collections.abc.Callable
        ``publish(dict_parts)`` registers ``{part index: CSV lines}`` as the published parts of
        ``Empresas`` and returns the patched downloader mock.
    """

    def publish(  # complexity-ok: builds the fake share
        dict_parts: dict[int, list[str]],
    ) -> MagicMock:
        dict_paths = {}
        for int_part, list_lines in dict_parts.items():
            dict_paths[f"Empresas{int_part}.zip"] = tmp_path / f"src_{int_part}.zip"
            _write_part_zip(dict_paths[f"Empresas{int_part}.zip"], list_lines)
        list_entries = [
            WebdavEntry(str_name, False, 1, f'"etag-{str_name}"', datetime.now(timezone.utc))
            for str_name in dict_paths
        ]
        monkeypatch.setattr(_multipart, "list_files", lambda _str_month: list_entries)

        def fake_download(str_url: str, path_dest: Path) -> tuple[Path, str]:
            str_name = str_url.rsplit("/", 1)[-1]
            path_dest.write_bytes(dict_paths[str_name].read_bytes())
            return path_dest, f'"etag-{str_name}"'

        mock_download = MagicMock(side_effect=fake_download)
        monkeypatch.setattr(_multipart, "download_file_streaming", mock_download)
        return mock_download

    return publish
