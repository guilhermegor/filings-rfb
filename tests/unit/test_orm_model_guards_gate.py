"""Unit tests for the ORM model-definition guards gate (blueprintx#361; offline, no network).

Each guard needs BOTH directions proven: the dangerous form must FAIL naming the file and the
line; the safe form must PASS. A gate that cannot fail is reporting its own blindness as OK —
the exact failure mode this repo's gates exist to prevent.
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


gate = _load("check_orm_model_guards")


def _python_file(path_dir: Path, str_source: str, str_name: str = "sample.py") -> Path:
    """Write a Python source file and return its path.

    Parameters
    ----------
    path_dir : pathlib.Path
        Directory to write into.
    str_source : str
        File contents.
    str_name : str, optional
        Filename to use, by default ``"sample.py"``.

    Returns
    -------
    pathlib.Path
        The written file.
    """
    path_file = path_dir / str_name
    path_file.write_text(str_source, encoding="utf-8")
    return path_file


@pytest.fixture
def list_bitwise_and_problems(tmp_path: Path) -> list[str]:
    """Return the findings for ``&`` inside ``.where(...)``.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    list[str]
        The gate's findings.
    """
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import select\n\n"
        "stmt = select(User).where(User.age == 18 & User.is_active == True)\n",
    )
    return gate.check_python_file(path_file)[0]


def test_bitwise_and_inside_where_is_reported(list_bitwise_and_problems: list[str]) -> None:
    """``&`` inside ``.where(...)`` is a precedence hazard, flagged unconditionally.

    Parameters
    ----------
    list_bitwise_and_problems : list[str]
        The gate's findings.
    """
    assert len(list_bitwise_and_problems) == 1


@pytest.mark.parametrize("str_needle", ["bitwise operator", "orm-guard-ok:"])
def test_bitwise_and_finding_names_the_hazard_and_the_hatch(
    list_bitwise_and_problems: list[str], str_needle: str
) -> None:
    """The finding names the hazard and how to justify a deliberate exception.

    Parameters
    ----------
    list_bitwise_and_problems : list[str]
        The gate's findings.
    str_needle : str
        Text the finding must contain.
    """
    assert str_needle in list_bitwise_and_problems[0]


def test_bitwise_or_inside_filter_is_reported(tmp_path: Path) -> None:
    """``|`` inside ``.filter(...)`` is the same hazard as ``&`` inside ``.where(...)``."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy.orm import Session\n\nsession.query(User).filter(User.a | User.b)\n",
    )

    assert len(gate.check_python_file(path_file)[0]) == 1


def test_and_or_house_form_inside_where_passes(tmp_path: Path) -> None:
    """``and_()``/``or_()`` cannot be mis-parenthesised and must never be flagged."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import select, and_\n\n"
        "stmt = select(User).where(and_(User.age == 18, User.is_active == True))\n",
    )

    assert gate.check_python_file(path_file)[0] == []


def test_bitwise_operator_outside_where_filter_is_not_flagged(tmp_path: Path) -> None:
    """A ``&`` used elsewhere (e.g. real bit-flag arithmetic) is out of this gate's scope."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import select\n\nint_mask = 0b1010 & 0b0110\n",
    )

    assert gate.check_python_file(path_file)[0] == []


def test_no_sqlalchemy_import_skips_the_bitwise_check(tmp_path: Path) -> None:
    """A file with no ``sqlalchemy`` import is out of scope (Django ``Q`` objects use ``&``).

    The receiver is not named like a frame, so only the import scope check can skip this.
    """
    path_file = _python_file(tmp_path, "qs.filter(Q(a) & Q(b))\n")

    assert gate.check_python_file(path_file)[0] == []


@pytest.fixture
def tuple_two_bases_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> tuple:
    """Run the gate over a tree holding two ``DeclarativeBase`` subclasses.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway project root.
    monkeypatch : pytest.MonkeyPatch
        Used to run the gate from the project root.
    capsys : pytest.CaptureFixture[str]
        Captures the gate's message.

    Returns
    -------
    tuple
        ``(int_code, str_out)``.
    """
    path_src = tmp_path / "src"
    path_src.mkdir()
    (path_src / "a.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\n\nclass Base(DeclarativeBase):\n\tpass\n",
        encoding="utf-8",
    )
    (path_src / "b.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\n\nclass Base2(DeclarativeBase):\n\tpass\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    int_code = gate.main()
    return int_code, "".join(capsys.readouterr())


def test_two_declarative_base_subclasses_across_the_tree_are_reported(
    tuple_two_bases_run: tuple,
) -> None:
    """A second ``DeclarativeBase`` subclass anywhere in ``src/`` fails the run.

    Parameters
    ----------
    tuple_two_bases_run : tuple
        ``(int_code, str_out)``.
    """
    assert tuple_two_bases_run[0] == 1


@pytest.mark.parametrize("str_name", ["a.py", "b.py"])
def test_two_declarative_bases_name_both_files(tuple_two_bases_run: tuple, str_name: str) -> None:
    """The violation is for BOTH files, so both are named.

    Parameters
    ----------
    tuple_two_bases_run : tuple
        ``(int_code, str_out)``.
    str_name : str
        A file the report must name.
    """
    assert str_name in tuple_two_bases_run[1]


def test_single_declarative_base_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exactly one ``DeclarativeBase`` subclass in the tree is the expected, safe shape."""
    path_src = tmp_path / "src"
    path_src.mkdir()
    (path_src / "a.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\n\nclass Base(DeclarativeBase):\n\tpass\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert gate.main() == 0


@pytest.fixture
def list_create_all_problems(tmp_path: Path) -> list[str]:
    """Return the findings for ``Base.metadata.create_all(...)`` at import time.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    list[str]
        The gate's findings.
    """
    path_file = _python_file(
        tmp_path, "from .base import Base\n\nBase.metadata.create_all(engine)\n"
    )
    return gate.check_python_file(path_file)[0]


def test_module_scope_create_all_is_reported(list_create_all_problems: list[str]) -> None:
    """``Base.metadata.create_all(...)`` at import time is a violation.

    Parameters
    ----------
    list_create_all_problems : list[str]
        The gate's findings.
    """
    assert len(list_create_all_problems) == 1


def test_module_scope_create_all_finding_names_the_scope(
    list_create_all_problems: list[str],
) -> None:
    """The finding says the call ran at MODULE scope.

    Parameters
    ----------
    list_create_all_problems : list[str]
        The gate's findings.
    """
    assert "MODULE scope" in list_create_all_problems[0]


def test_create_all_inside_a_function_passes(tmp_path: Path) -> None:
    """``create_all`` deferred into a function (run after models import) is the safe shape."""
    path_file = _python_file(
        tmp_path,
        "from .base import Base\n\ndef init() -> None:\n\tBase.metadata.create_all(engine)\n",
    )

    assert gate.check_python_file(path_file)[0] == []


def test_unrelated_create_all_method_is_not_flagged(tmp_path: Path) -> None:
    """A ``.create_all()`` not chained off ``.metadata`` is out of scope (low false-positive)."""
    path_file = _python_file(tmp_path, "cache.create_all()\n")

    assert gate.check_python_file(path_file)[0] == []


@pytest.fixture
def list_two_mixin_problems(tmp_path: Path) -> list[str]:
    """Return the findings for two mixins that both declare ``__table_args__``.

    SQLAlchemy does not concatenate them. Attribute lookup takes ``MixinA``'s and drops
    ``MixinB``'s whole declaration, so the shared ``uq_x`` name never collides at runtime and
    the real defect is that ``MixinB``'s constraints are silently gone.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    list[str]
        The gate's findings.
    """
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import UniqueConstraint\n\n"
        "class MixinA:\n"
        "\t__table_args__ = (UniqueConstraint('a', name='uq_x'),)\n\n"
        "class MixinB:\n"
        "\t__table_args__ = (UniqueConstraint('b', name='uq_x'),)\n\n"
        "class Model(MixinA, MixinB):\n"
        "\tpass\n",
    )
    return gate.check_python_file(path_file)[0]


def test_two_mixins_declaring_table_args_report_the_shadowing(
    list_two_mixin_problems: list[str],
) -> None:
    """Two mixins declaring ``__table_args__`` do not compose: the second one is discarded.

    Parameters
    ----------
    list_two_mixin_problems : list[str]
        The gate's findings.
    """
    assert len(list_two_mixin_problems) == 1


@pytest.mark.parametrize("str_needle", ["MixinB", "discards", "orm-guard-ok:"])
def test_two_mixin_finding_names_the_shadowed_mixin(
    list_two_mixin_problems: list[str], str_needle: str
) -> None:
    """The finding names the shadowed mixin, says it is discarded, and names the hatch.

    Parameters
    ----------
    list_two_mixin_problems : list[str]
        The gate's findings.
    str_needle : str
        Text the finding must contain.
    """
    assert str_needle in list_two_mixin_problems[0]


def test_mapped_parent_and_child_each_declaring_table_args_is_clean(tmp_path: Path) -> None:
    """A mapped parent keeps its own table's ``__table_args__`` — only mixins are shadowed."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import UniqueConstraint\n\n"
        "class Parent:\n"
        "\t__tablename__ = 'parent'\n"
        "\t__table_args__ = (UniqueConstraint('a', name='uq_parent'),)\n\n"
        "class Child(Parent):\n"
        "\t__tablename__ = 'child'\n"
        "\t__table_args__ = (UniqueConstraint('b', name='uq_child'),)\n",
    )

    assert gate.check_python_file(path_file)[0] == []


def test_pandas_mask_on_a_df_receiver_is_not_flagged(tmp_path: Path) -> None:
    """A frame named by the house ``df_`` prefix is pandas, whose masks use ``&`` by design."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import select\n\ndf_out = df_in.where(mask_a & mask_b)\n",
    )

    assert gate.check_python_file(path_file)[0] == []


@pytest.fixture
def list_distinct_names_problems(tmp_path: Path) -> list[str]:
    """Return the findings for two mixins declaring ``__table_args__`` with DISTINCT names.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    list[str]
        The gate's findings.
    """
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import UniqueConstraint\n\n"
        "class MixinA:\n"
        "\t__table_args__ = (UniqueConstraint('a', name='uq_x'),)\n\n"
        "class MixinB:\n"
        "\t__table_args__ = (UniqueConstraint('b', name='uq_y'),)\n\n"
        "class Model(MixinA, MixinB):\n"
        "\tpass\n",
    )
    return gate.check_python_file(path_file)[0]


def test_distinct_constraint_names_across_mixins_still_shadow(
    list_distinct_names_problems: list[str],
) -> None:
    """Distinct names do not save the model, ``uq_y`` goes with ``MixinB``'s declaration.

    Parameters
    ----------
    list_distinct_names_problems : list[str]
        The gate's findings.
    """
    assert len(list_distinct_names_problems) == 1


def test_distinct_constraint_names_finding_names_the_shadowed_mixin(
    list_distinct_names_problems: list[str],
) -> None:
    """The finding names the mixin whose declaration is dropped.

    Parameters
    ----------
    list_distinct_names_problems : list[str]
        The gate's findings.
    """
    assert "MixinB" in list_distinct_names_problems[0]


def test_one_mixin_declaring_table_args_is_clean(tmp_path: Path) -> None:
    """Only one declaration in the MRO: nothing is shadowed, nothing to report."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import UniqueConstraint\n\n"
        "class MixinA:\n"
        "\t__table_args__ = (UniqueConstraint('a', name='uq_x'),)\n\n"
        "class MixinB:\n"
        "\tpass\n\n"
        "class Model(MixinA, MixinB):\n"
        "\tpass\n",
    )

    assert gate.check_python_file(path_file)[0] == []


@pytest.fixture
def list_duplicate_name_problems(tmp_path: Path) -> list[str]:
    """Return the findings for two constraints sharing a ``name=`` inside ONE ``__table_args__``.

    A genuine collision: both are real, both reach the table, and one loses.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    list[str]
        The gate's findings.
    """
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import UniqueConstraint\n\n"
        "class Model:\n"
        "\t__table_args__ = (\n"
        "\t\tUniqueConstraint('a', name='uq_x'),\n"
        "\t\tUniqueConstraint('b', name='uq_x'),\n"
        "\t)\n",
    )
    return gate.check_python_file(path_file)[0]


def test_duplicate_name_inside_the_effective_declaration_is_reported(
    list_duplicate_name_problems: list[str],
) -> None:
    """The duplicate check survives, narrowed to the one declaration that is live.

    Parameters
    ----------
    list_duplicate_name_problems : list[str]
        The gate's findings.
    """
    assert len(list_duplicate_name_problems) == 1


def test_duplicate_name_finding_names_the_constraint(
    list_duplicate_name_problems: list[str],
) -> None:
    """The finding names the colliding constraint.

    Parameters
    ----------
    list_duplicate_name_problems : list[str]
        The gate's findings.
    """
    assert "uq_x" in list_duplicate_name_problems[0]


@pytest.fixture
def list_empty_table_args_problems(tmp_path: Path) -> list[str]:
    """Return the findings for a mixin declaring an empty ``__table_args__`` before another.

    Declaring an empty tuple is a declaration: it shadows, and must be reported. This is why
    declaration presence is tracked separately from the list of names — an empty name list
    from ``_table_args_names`` is indistinguishable from "no ``__table_args__`` at all"
    unless something else asks the question.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    list[str]
        The gate's findings.
    """
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import UniqueConstraint\n\n"
        "class MixinA:\n"
        "\t__table_args__ = ()\n\n"
        "class MixinB:\n"
        "\t__table_args__ = (UniqueConstraint('b', name='uq_y'),)\n\n"
        "class Model(MixinA, MixinB):\n"
        "\tpass\n",
    )
    return gate.check_python_file(path_file)[0]


def test_an_empty_table_args_still_shadows_a_base_declaration(
    list_empty_table_args_problems: list[str],
) -> None:
    """An empty ``__table_args__`` shadows a later declaration, so it is reported once.

    Parameters
    ----------
    list_empty_table_args_problems : list[str]
        The gate's findings.
    """
    assert len(list_empty_table_args_problems) == 1


def test_an_empty_table_args_finding_names_the_shadowed_mixin(
    list_empty_table_args_problems: list[str],
) -> None:
    """The finding names the mixin whose declaration is dropped.

    Parameters
    ----------
    list_empty_table_args_problems : list[str]
        The gate's findings.
    """
    assert "MixinB" in list_empty_table_args_problems[0]


def test_single_class_with_no_bases_never_flags_its_own_constraint(tmp_path: Path) -> None:
    """A lone model with one constraint has nothing to collide with."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import UniqueConstraint\n\n"
        "class Model:\n"
        "\t__table_args__ = (UniqueConstraint('a', name='uq_x'),)\n",
    )

    assert gate.check_python_file(path_file)[0] == []


def test_escape_hatch_with_reason_suppresses_the_finding(tmp_path: Path) -> None:
    """A written reason after the marker is accepted."""
    path_file = _python_file(
        tmp_path,
        "from .base import Base\n\n"
        "Base.metadata.create_all(engine)  # orm-guard-ok: single-tenant script, reviewed\n",
    )

    assert gate.check_python_file(path_file)[0] == []


def test_escape_hatch_with_empty_reason_still_fails(tmp_path: Path) -> None:
    """A bare marker with no reason (or whitespace only) is rejected, not accepted."""
    path_file = _python_file(
        tmp_path,
        "from .base import Base\n\nBase.metadata.create_all(engine)  # orm-guard-ok:   \n",
    )

    assert len(gate.check_python_file(path_file)[0]) == 1


def test_main_skips_when_src_is_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``src/`` directory at all is a legitimate skip."""
    monkeypatch.chdir(tmp_path)

    assert gate.main() == 0


def test_main_fails_on_zero_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``src/`` exists but holds no Python files — that must FAIL, not pass silently."""
    (tmp_path / "src").mkdir()
    monkeypatch.chdir(tmp_path)

    assert gate.main() == 1


def test_main_passes_on_a_clean_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real file with no violations reports success."""
    path_src = tmp_path / "src"
    path_src.mkdir()
    (path_src / "mod.py").write_text("int_x = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert gate.main() == 0


_SA = "from sqlalchemy import UniqueConstraint, Index, select\n"


def test_bitwise_invert_inside_where_is_reported(tmp_path: Path) -> None:
    """``~`` binds tighter than ``==`` in the same way ``&`` does, so it is the same hazard."""
    path_file = _python_file(tmp_path, _SA + "stmt = select(U).where(~U.active)\n")

    assert len(gate.check_python_file(path_file)[0]) == 1


def test_model_composing_its_mixins_explicitly_is_clean(tmp_path: Path) -> None:
    """The fix the shadow message recommends must itself pass, with neither mixin discarded."""
    path_file = _python_file(
        tmp_path,
        _SA + "class MixinA:\n"
        "\t__table_args__ = (UniqueConstraint('a', name='uq_a'),)\n\n"
        "class MixinB:\n"
        "\t__table_args__ = (UniqueConstraint('b', name='uq_b'),)\n\n"
        "class Model(MixinA, MixinB):\n"
        "\t__table_args__ = MixinA.__table_args__ + MixinB.__table_args__\n",
    )

    assert gate.check_python_file(path_file)[0] == []


def test_composed_mixins_that_repeat_a_name_are_reported(tmp_path: Path) -> None:
    """Composing is not a free pass: the repeated name now sits in ONE effective declaration."""
    path_file = _python_file(
        tmp_path,
        _SA + "class MixinA:\n"
        "\t__table_args__ = (UniqueConstraint('a', name='uq_x'),)\n\n"
        "class MixinB:\n"
        "\t__table_args__ = (UniqueConstraint('b', name='uq_x'),)\n\n"
        "class Model(MixinA, MixinB):\n"
        "\t__table_args__ = MixinA.__table_args__ + MixinB.__table_args__\n",
    )

    assert "uq_x" in gate.check_python_file(path_file)[0][0]


def test_diamond_reports_the_discarded_class_not_the_live_one(tmp_path: Path) -> None:
    """Python's real MRO is Model, TsMixin, AuditMixin, Common: ``AuditMixin`` wins."""
    path_file = _python_file(
        tmp_path,
        _SA + "class Common:\n"
        "\t__table_args__ = ()\n\n"
        "class TsMixin(Common):\n"
        "\tpass\n\n"
        "class AuditMixin(Common):\n"
        "\t__table_args__ = (UniqueConstraint('a', name='uq_a'),)\n\n"
        "class Model(TsMixin, AuditMixin):\n"
        "\tpass\n",
    )

    list_problems, _ = gate.check_python_file(path_file)

    assert [p.split("'")[1] for p in list_problems] == ["Common"]


def test_declared_attr_table_args_is_seen_as_a_declaration(tmp_path: Path) -> None:
    """A ``@declared_attr`` mixin wins the MRO here, so the plain-assign mixin is the one lost."""
    path_file = _python_file(
        tmp_path,
        _SA + "class MixinA:\n"
        "\t@declared_attr\n"
        "\tdef __table_args__(cls):\n"
        "\t\treturn (UniqueConstraint('a', name='uq_a'),)\n\n"
        "class MixinB:\n"
        "\t__table_args__ = (UniqueConstraint('b', name='uq_b'),)\n\n"
        "class Model(MixinA, MixinB):\n"
        "\tpass\n",
    )

    list_problems, _ = gate.check_python_file(path_file)

    assert [p.split("'")[1] for p in list_problems] == ["MixinB"]


def test_create_all_under_the_main_guard_is_not_flagged(tmp_path: Path) -> None:
    """``if __name__ == "__main__":`` never runs on import, which is what the finding describes."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy.orm import DeclarativeBase\n"
        "class Base(DeclarativeBase): pass\n"
        "if __name__ == '__main__':\n"
        "\tBase.metadata.create_all(engine)\n",
    )

    assert gate.check_python_file(path_file)[0] == []


def test_a_mixin_inherited_by_two_models_is_reported_once(tmp_path: Path) -> None:
    """One defect in the mixin is one finding, however many models inherit it."""
    path_file = _python_file(
        tmp_path,
        _SA + "class Mx:\n"
        "\t__table_args__ = (\n"
        "\t\tUniqueConstraint('a', name='uq_x'),\n"
        "\t\tUniqueConstraint('b', name='uq_x'),\n"
        "\t)\n\n"
        "class M1(Mx):\n\tpass\n\n"
        "class M2(Mx):\n\tpass\n",
    )

    assert len(gate.check_python_file(path_file)[0]) == 1


def test_duplicate_index_names_given_positionally_are_reported(tmp_path: Path) -> None:
    """``Index`` takes its name as the first positional argument, not ``name=``."""
    path_file = _python_file(
        tmp_path,
        _SA + "class M:\n\t__table_args__ = (Index('ix_x', 'a'), Index('ix_x', 'b'))\n",
    )

    assert "ix_x" in gate.check_python_file(path_file)[0][0]


def test_a_nested_class_does_not_overwrite_a_model_of_the_same_name(tmp_path: Path) -> None:
    """Only module-level classes are models; an inner ``Meta`` must not shadow a real one."""
    path_file = _python_file(
        tmp_path,
        _SA + "class Meta:\n"
        "\t__table_args__ = (UniqueConstraint('a', name='uq_a'),)\n\n"
        "class Model(Meta):\n"
        "\tclass Meta:\n"
        "\t\tpass\n\n"
        "\t__table_args__ = (UniqueConstraint('b', name='uq_b'),)\n",
    )

    list_problems, _ = gate.check_python_file(path_file)

    assert [p.split("'")[1] for p in list_problems] == ["Meta"]


def test_base_variants_beyond_declarative_base_are_found(tmp_path: Path) -> None:
    """``DeclarativeBaseNoMeta`` and ``registry().generate_base()`` also create a second Base."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy.orm import DeclarativeBaseNoMeta, registry\n"
        "class B1(DeclarativeBaseNoMeta): pass\n"
        "B2 = registry().generate_base()\n",
    )

    assert len(gate.check_python_file(path_file)[1]) == 2
