"""Unit tests for the read-modify-write race gate (blueprintx#385; offline, no git/network).

**The negative control is the point** — same rule as ``test_function_length_gate.py``. #385
measured ZERO instances of the arithmetic form anywhere in ``templates/`` today, so this gate's
should-fail witness has no real file to replay: every fixture below is synthetic, and that is
the deliberate consequence the issue names, not an oversight.

Each test either proves the gate FIRES on the exact shape #385 scopes in (row 1 of its
decidability table: an attribute reassigned from an ARITHMETIC expression over its own prior
value, read via ``session.get``/``.query(...).first()``/``.one()``, with no lock and no
``version_id_col``), or pins a measured reason it must NOT fire — row 2 ("read then write, no
lock") is explicitly OUT OF SCOPE, and firing on it would make the gate 100% noise on every ORM
``update()`` in existence.
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


gate = _load("check_rmw_race")


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


def test_arithmetic_write_after_session_get_is_reported(tmp_path: Path) -> None:
    """The canonical race: `.get()` read, arithmetic write, no lock, no version column."""
    path_file = _python_file(
        tmp_path,
        "class Product:\n"
        '\t__tablename__ = "product"\n'
        "\n\n"
        "def decrement_stock(session, product_id, quantity):\n"
        "\trecord = session.get(Product, product_id)\n"
        "\trecord.stock = record.stock - quantity\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 1


@pytest.mark.parametrize("str_which", ["location", "source"])
def test_arithmetic_write_after_session_get_names_file_and_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], str_which: str
) -> None:
    """The message must name the offending file and line — 'possible race' teaches nothing.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest throwaway directory holding the probe module.
    capsys : pytest.CaptureFixture
        Captures the gate's output.
    str_which : str
        Which half of the identification is under test.
    """
    path_file = _python_file(
        tmp_path,
        "class Product:\n"
        '\t__tablename__ = "product"\n'
        "\n\n"
        "def decrement_stock(session, product_id, quantity):\n"
        "\trecord = session.get(Product, product_id)\n"
        "\trecord.stock = record.stock - quantity\n"
        "\tsession.flush()\n",
    )

    gate.check_file(str(path_file))
    dict_expected = {
        "location": f"{path_file}:7",
        "source": "record.stock = record.stock - quantity",
    }

    assert dict_expected[str_which] in capsys.readouterr().out


def test_augmented_assignment_form_is_also_reported(tmp_path: Path) -> None:
    """`x.qty -= n` IS `x.qty = x.qty - n` — the augmented form must fire identically."""
    path_file = _python_file(
        tmp_path,
        "class Order:\n"
        '\t__tablename__ = "order"\n'
        "\n\n"
        "def decrement_stock(session, order_id, quantity):\n"
        "\trecord = session.get(Order, order_id)\n"
        "\trecord.stock -= quantity\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 1


def test_query_first_chain_with_a_model_is_reported(tmp_path: Path) -> None:
    """The `.query(Model)....first()` chain form is gated too, not only `.get()`."""
    path_file = _python_file(
        tmp_path,
        "class Order:\n"
        '\t__tablename__ = "order"\n'
        "\n\n"
        "def decrement_stock(session, order_id, quantity):\n"
        "\trecord = session.query(Order).filter(Order.id == order_id).first()\n"
        "\trecord.stock = record.stock - quantity\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 1


def test_with_for_update_kwarg_on_session_get_silences_it(tmp_path: Path) -> None:
    """A pessimistic lock on the read removes the race — must NOT fire."""
    path_file = _python_file(
        tmp_path,
        "class Product:\n"
        '\t__tablename__ = "product"\n'
        "\n\n"
        "def decrement_stock(session, product_id, quantity):\n"
        "\trecord = session.get(Product, product_id, with_for_update=True)\n"
        "\trecord.stock = record.stock - quantity\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 0


def test_with_for_update_chained_call_silences_it(tmp_path: Path) -> None:
    """A chained `.with_for_update()` on the query form removes the race too."""
    path_file = _python_file(
        tmp_path,
        "class Order:\n"
        '\t__tablename__ = "order"\n'
        "\n\n"
        "def decrement_stock(session, order_id, quantity):\n"
        "\trecord = (\n"
        "\t\tsession.query(Order).filter(Order.id == order_id).with_for_update().first()\n"
        "\t)\n"
        "\trecord.stock = record.stock - quantity\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 0


def test_version_id_col_on_the_model_silences_it(tmp_path: Path) -> None:
    """Optimistic locking via `version_id_col` on the same-file model removes the race."""
    path_file = _python_file(
        tmp_path,
        "class Product:\n"
        '\t__tablename__ = "product"\n'
        '\t__mapper_args__ = {"version_id_col": "version"}\n'
        "\n\n"
        "def decrement_stock(session, product_id, quantity):\n"
        "\trecord = session.get(Product, product_id)\n"
        "\trecord.stock = record.stock - quantity\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 0


def test_sql_side_update_where_form_is_never_flagged(tmp_path: Path) -> None:
    """The recommended SQL-side fix must never itself be flagged.

    `UPDATE ... SET x = x - n WHERE ... AND x >= n` is not ORM code at all, so it never
    enters this gate's read/write tracking. Must stay clean.
    """
    path_file = _python_file(
        tmp_path,
        "def decrement_stock(session, product_id, quantity):\n"
        "\tsession.execute(\n"
        '\t\t"UPDATE product SET stock = stock - :q WHERE id = :id AND stock >= :q",\n'
        '\t\t{"q": quantity, "id": product_id},\n'
        "\t)\n",
    )

    assert gate.check_file(str(path_file)) == 0


def test_escape_hatch_with_a_reason_silences_the_finding(tmp_path: Path) -> None:
    """A single-writer migration script legitimately reads-then-writes arithmetically."""
    path_file = _python_file(
        tmp_path,
        "class Order:\n"
        '\t__tablename__ = "order"\n'
        "\n\n"
        "def decrement_stock(session, order_id, quantity):\n"
        "\trecord = session.get(Order, order_id)\n"
        "\trecord.stock = record.stock - quantity  # rmw-ok: single-writer offline migration\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 0


def test_a_bare_escape_hatch_with_no_reason_is_rejected(tmp_path: Path) -> None:
    """The reason is required — a bare marker must not satisfy the gate."""
    path_file = _python_file(
        tmp_path,
        "class Order:\n"
        '\t__tablename__ = "order"\n'
        "\n\n"
        "def decrement_stock(session, order_id, quantity):\n"
        "\trecord = session.get(Order, order_id)\n"
        "\trecord.stock = record.stock - quantity  # rmw-ok:\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 1


def test_a_plain_full_record_overwrite_is_not_flagged(tmp_path: Path) -> None:
    """Read-then-write with NO arithmetic (row 2 of #385's table) must never fire.

    This is the shipped `repository.update()` shape (`record.data = json.dumps(entity)`) —
    every ORM `update()` in existence reads then writes, so gating this would be 100% noise.
    """
    path_file = _python_file(
        tmp_path,
        "class Record:\n"
        '\t__tablename__ = "record"\n'
        "\n\n"
        "def update(session, entity_id, entity):\n"
        "\trecord = session.get(Record, entity_id)\n"
        "\tif record is None:\n"
        "\t\treturn None\n"
        "\trecord.data = entity\n"
        "\tsession.flush()\n"
        "\treturn record\n",
    )

    assert gate.check_file(str(path_file)) == 0


def test_an_unrelated_first_call_with_no_query_model_is_not_flagged(tmp_path: Path) -> None:
    """A `.first()` call with no `.query(Model)` in its chain is not pinned to a model.

    Firing here would be the false-positive risk #385 calls out for the wider "any read then
    write" shape — a `.first()`-like helper exists on plenty of non-ORM objects.
    """
    path_file = _python_file(
        tmp_path,
        "def touch_first(items):\n"
        "\tfirst_item = build_list(items).first()\n"
        "\tfirst_item.value = first_item.value - 1\n",
    )

    assert gate.check_file(str(path_file)) == 0


def test_a_race_in_one_function_does_not_leak_into_a_sibling(tmp_path: Path) -> None:
    """Entity tracking is scoped per function, not shared across sibling functions.

    The same variable name in another function with a safe read must not inherit the
    unsafe one's violation, or vice versa.
    """
    path_file = _python_file(
        tmp_path,
        "class Order:\n"
        '\t__tablename__ = "order"\n'
        "\n\n"
        "def unsafe(session, order_id, quantity):\n"
        "\trecord = session.get(Order, order_id)\n"
        "\trecord.stock = record.stock - quantity\n"
        "\n\n"
        "def safe(session, order_id, quantity):\n"
        "\trecord = session.get(Order, order_id, with_for_update=True)\n"
        "\trecord.stock = record.stock - quantity\n",
    )

    assert gate.check_file(str(path_file)) == 1


def test_discovery_finds_nothing_when_there_is_no_src_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero discovered files under `src/` is what makes the CLI guard fail, not pass.

    The `__main__` block exits 1 when `_source_files()` returns an empty list — this pins
    the seam that decision reads, the same discovery-guard shape as the sibling gates.
    """
    monkeypatch.chdir(tmp_path)

    assert gate._source_files() == []  # noqa: SLF001 — testing the discovery seam directly


def test_with_for_update_false_is_not_a_lock(tmp_path: Path) -> None:
    """Presence of the keyword is not protection; `False` means no lock."""
    path_file = _python_file(
        tmp_path,
        "class Product:\n"
        '\t__tablename__ = "product"\n'
        "\n\n"
        "def decrement_stock(session, product_id, quantity):\n"
        "\trecord = session.get(Product, product_id, with_for_update=False)\n"
        "\trecord.stock = record.stock - quantity\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 1


def test_with_for_update_none_is_not_a_lock(tmp_path: Path) -> None:
    """`None` is the other falsey spelling and means no lock either."""
    path_file = _python_file(
        tmp_path,
        "class Product:\n"
        '\t__tablename__ = "product"\n'
        "\n\n"
        "def decrement_stock(session, product_id, quantity):\n"
        "\trecord = session.get(Product, product_id, with_for_update=None)\n"
        "\trecord.stock = record.stock - quantity\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 1


def test_with_for_update_true_still_suppresses(tmp_path: Path) -> None:
    """The control: evaluating the value must not blind the gate to a genuine lock."""
    path_file = _python_file(
        tmp_path,
        "class Product:\n"
        '\t__tablename__ = "product"\n'
        "\n\n"
        "def decrement_stock(session, product_id, quantity):\n"
        "\trecord = session.get(Product, product_id, with_for_update=True)\n"
        "\trecord.stock = record.stock - quantity\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 0


def test_an_unlocked_branch_is_not_masked_by_a_locked_one(tmp_path: Path) -> None:
    """Two definitions of one name: the unlocked branch decides, whatever the source order."""
    path_file = _python_file(
        tmp_path,
        "class Product:\n"
        '\t__tablename__ = "product"\n'
        "\n\n"
        "def decrement_stock(session, product_id, quantity, use_lock):\n"
        "\tif use_lock:\n"
        "\t\trecord = session.get(Product, product_id, with_for_update=True)\n"
        "\telse:\n"
        "\t\trecord = session.get(Product, product_id)\n"
        "\trecord.stock = record.stock - quantity\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 1


def test_a_string_mentioning_version_id_col_is_not_a_version_column(tmp_path: Path) -> None:
    """A gate turned off by writing its own keyword in prose is no gate."""
    path_file = _python_file(
        tmp_path,
        "class Product:\n"
        '\t__tablename__ = "product"\n'
        '\tstr_note = "todo: consider version_id_col here"\n'
        "\n\n"
        "def decrement_stock(session, product_id, quantity):\n"
        "\trecord = session.get(Product, product_id)\n"
        "\trecord.stock = record.stock - quantity\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 1


def test_a_declared_version_id_col_still_suppresses(tmp_path: Path) -> None:
    """The control: parsing must not blind the gate to a real optimistic lock."""
    path_file = _python_file(
        tmp_path,
        "class Product:\n"
        '\t__tablename__ = "product"\n'
        '\t__mapper_args__ = {"version_id_col": version}\n'
        "\n\n"
        "def decrement_stock(session, product_id, quantity):\n"
        "\trecord = session.get(Product, product_id)\n"
        "\trecord.stock = record.stock - quantity\n"
        "\tsession.flush()\n",
    )

    assert gate.check_file(str(path_file)) == 0
