"""Unit tests for the identifier-masking gate (blueprintx#355 item 4; offline, no network).

Same discipline as ``test_sql_guards_gate.py``: each detection shape needs BOTH directions
proven (the dangerous form fails naming the file, line, value and escape hatch; the safe
form passes), plus false-positive guards for the patterns that look similar but are not the
bug — an unmasked comparison, and a masked value compared against an unrelated column.
"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


_BIN = Path(__file__).resolve().parents[2] / "bin"


def _load(str_name: str) -> ModuleType:
    """Load a ``bin/`` script by path (``bin/`` is not a package).

    Parameters
    ----------
    str_name : str
        Module stem under ``bin/``.

    Returns
    -------
    ModuleType
        The imported module.
    """
    cls_spec = importlib.util.spec_from_file_location(str_name, _BIN / f"{str_name}.py")
    cls_module = importlib.util.module_from_spec(cls_spec)
    sys.modules[str_name] = cls_module
    cls_spec.loader.exec_module(cls_module)
    return cls_module


gate = _load("check_identifier_masking")


def _python_file(path_dir: Path, str_source: str) -> Path:
    """Write a Python source file and return its path.

    Parameters
    ----------
    path_dir : pathlib.Path
        Directory to write into.
    str_source : str
        File contents.

    Returns
    -------
    pathlib.Path
        The written file.
    """
    path_file = path_dir / "sample.py"
    path_file.write_text(str_source, encoding="utf-8")
    return path_file


@pytest.fixture
def tuple_masked_cpf_sql(tmp_path: Path) -> tuple:
    """Return the findings for a hardcoded masked CPF inside a SQL string literal.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    tuple
        ``(path_file, list_problems)``.
    """
    path_file = _python_file(
        tmp_path,
        "query = \"SELECT * FROM users WHERE cpf = '123.456.789-01'\"\n",
    )
    return path_file, gate.check_python_file(path_file)


def test_masked_cpf_in_sql_string_literal_is_reported(tuple_masked_cpf_sql: tuple) -> None:
    """A hardcoded masked CPF in a SQL string matches zero rows, silently.

    Parameters
    ----------
    tuple_masked_cpf_sql : tuple
        ``(path_file, list_problems)``.
    """
    assert len(tuple_masked_cpf_sql[1]) == 1


def test_masked_cpf_finding_names_the_value(tuple_masked_cpf_sql: tuple) -> None:
    """The finding quotes the masked value it objects to.

    Parameters
    ----------
    tuple_masked_cpf_sql : tuple
        ``(path_file, list_problems)``.
    """
    assert "123.456.789-01" in tuple_masked_cpf_sql[1][0]


def test_masked_cpf_finding_names_the_file(tuple_masked_cpf_sql: tuple) -> None:
    """The finding names the file it was found in.

    Parameters
    ----------
    tuple_masked_cpf_sql : tuple
        ``(path_file, list_problems)``.
    """
    assert str(tuple_masked_cpf_sql[0]) in tuple_masked_cpf_sql[1][0]


def test_masked_cpf_finding_names_the_escape_hatch(tuple_masked_cpf_sql: tuple) -> None:
    """The finding tells the reader how to justify a deliberate exception.

    Parameters
    ----------
    tuple_masked_cpf_sql : tuple
        ``(path_file, list_problems)``.
    """
    assert "identifier-mask-ok:" in tuple_masked_cpf_sql[1][0]


def test_masked_cnpj_alphanumeric_in_sql_string_literal_is_reported(tmp_path: Path) -> None:
    """The 2026 alphanumeric CNPJ mask format is matched too, not just legacy numeric."""
    path_file = _python_file(
        tmp_path,
        "query = \"SELECT * FROM firms WHERE cnpj = 'AB.CDE.FGH/1234-95'\"\n",
    )

    list_problems = gate.check_python_file(path_file)

    assert len(list_problems) == 1


def test_masked_cnpj_alphanumeric_finding_quotes_the_value(tmp_path: Path) -> None:
    """The alphanumeric-CNPJ finding quotes the masked value."""
    path_file = _python_file(
        tmp_path,
        "query = \"SELECT * FROM firms WHERE cnpj = 'AB.CDE.FGH/1234-95'\"\n",
    )

    assert "AB.CDE.FGH/1234-95" in gate.check_python_file(path_file)[0]


def test_unmasked_cpf_comparison_passes(tmp_path: Path) -> None:
    """An already-unmasked (digits-only) value never matches the mask format."""
    path_file = _python_file(
        tmp_path,
        "query = \"SELECT * FROM users WHERE cpf = '12345678901'\"\n",
    )

    assert gate.check_python_file(path_file) == []


def test_masked_value_compared_against_unrelated_column_passes(tmp_path: Path) -> None:
    """A CPF-shaped literal compared against an unrelated column is not this gate's bug."""
    path_file = _python_file(
        tmp_path,
        "query = \"SELECT * FROM logs WHERE reference_code = '123.456.789-01'\"\n",
    )

    assert gate.check_python_file(path_file) == []


def test_raw_sql_file_masked_cpf_is_reported(tmp_path: Path) -> None:
    """The same finding fires for a raw ``.sql`` file, the second surface SQL reaches us."""
    path_file = tmp_path / "query.sql"
    path_file.write_text("SELECT * FROM users WHERE cpf = '123.456.789-01'\n", encoding="utf-8")

    list_problems = gate._sql_file_problems(path_file)

    assert len(list_problems) == 1


def test_raw_sql_file_finding_quotes_the_value(tmp_path: Path) -> None:
    """The ``.sql`` finding quotes the masked value."""
    path_file = tmp_path / "query.sql"
    path_file.write_text("SELECT * FROM users WHERE cpf = '123.456.789-01'\n", encoding="utf-8")

    assert "123.456.789-01" in gate._sql_file_problems(path_file)[0]


def test_orm_attribute_comparison_masked_cpf_is_reported(tmp_path: Path) -> None:
    """``Model.cpf == "<masked>"`` is the ORM-builder shape of the same bug."""
    path_file = _python_file(
        tmp_path,
        'stmt = select(User).where(User.cpf == "123.456.789-01")\n',
    )

    list_problems = gate.check_python_file(path_file)

    assert len(list_problems) == 1


def test_orm_attribute_comparison_finding_quotes_the_value(tmp_path: Path) -> None:
    """The ORM-comparison finding quotes the masked value."""
    path_file = _python_file(
        tmp_path,
        'stmt = select(User).where(User.cpf == "123.456.789-01")\n',
    )

    assert "123.456.789-01" in gate.check_python_file(path_file)[0]


def test_orm_attribute_comparison_unmasked_cpf_passes(tmp_path: Path) -> None:
    """Comparing against the unmasked value (the correct form) must never be flagged."""
    path_file = _python_file(
        tmp_path,
        'stmt = select(User).where(User.cpf == unmask_cpf("123.456.789-01"))\n',
    )

    assert gate.check_python_file(path_file) == []


def test_filter_by_keyword_masked_cnpj_is_reported(tmp_path: Path) -> None:
    """``filter_by(cnpj="<masked>")`` is the keyword-argument shape of the same bug."""
    path_file = _python_file(
        tmp_path,
        'session.query(Company).filter_by(cnpj="12.345.678/0001-95")\n',
    )

    list_problems = gate.check_python_file(path_file)

    assert len(list_problems) == 1


def test_filter_by_keyword_finding_quotes_the_value(tmp_path: Path) -> None:
    """The ``filter_by`` finding quotes the masked value."""
    path_file = _python_file(
        tmp_path,
        'session.query(Company).filter_by(cnpj="12.345.678/0001-95")\n',
    )

    assert "12.345.678/0001-95" in gate.check_python_file(path_file)[0]


def test_filter_by_keyword_unmasked_value_passes(tmp_path: Path) -> None:
    """A digits-only keyword value is the correct, normalised form."""
    path_file = _python_file(
        tmp_path,
        'session.query(Company).filter_by(cnpj="12345678000195")\n',
    )

    assert gate.check_python_file(path_file) == []


def test_escape_hatch_with_reason_suppresses_finding(tmp_path: Path) -> None:
    """A written reason on the offending line suppresses the finding."""
    path_file = _python_file(
        tmp_path,
        "query = \"SELECT * FROM users WHERE cpf = '123.456.789-01'\"  "
        "# identifier-mask-ok: fixture oracle, reviewed in PR #355\n",
    )

    assert gate.check_python_file(path_file) == []


def test_escape_hatch_with_empty_reason_is_rejected(tmp_path: Path) -> None:
    """A bare marker with no reason is not a decision anyone made on purpose."""
    path_file = _python_file(
        tmp_path,
        "query = \"SELECT * FROM users WHERE cpf = '123.456.789-01'\"  # identifier-mask-ok:   \n",
    )

    assert len(gate.check_python_file(path_file)) == 1


def test_main_fails_when_src_present_but_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``src/`` existing but holding zero Python files must fail, not pass silently."""
    (tmp_path / "src").mkdir()
    monkeypatch.chdir(tmp_path)

    assert gate.main() == 1


def test_main_skips_when_src_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``src/`` directory at all is a graceful skip (e.g. a fresh scaffold)."""
    monkeypatch.chdir(tmp_path)

    assert gate.main() == 0


def test_main_scans_a_sql_only_src_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A tree holding only ``.sql`` files is scanned, not reported as nothing-scanned."""
    path_src = tmp_path / "src"
    path_src.mkdir()
    (path_src / "query.sql").write_text(
        "SELECT * FROM users WHERE cpf = '123.456.789-01'\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert gate.main() == 1


def test_main_passes_on_a_compliant_sql_only_src_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same tree with no masked comparison passes: zero Python files is not a failure."""
    path_src = tmp_path / "src"
    path_src.mkdir()
    (path_src / "query.sql").write_text(
        "SELECT * FROM users WHERE cpf = '12345678901'\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert gate.main() == 0
