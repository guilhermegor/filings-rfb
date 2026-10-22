"""Unit tests for the shared per-regime adapter pattern (issue #148).

The oracle is unit tests against a fixed, measured cutover date — never an invented one. The
issue names it explicitly: a monthly fund-profile series published 106 columns keyed
``CNPJ_FUNDO`` through period ``202311``, then 107 columns keyed
``TP_FUNDO_CLASSE``/``CNPJ_FUNDO_CLASSE`` from ``202312`` on. Every fixture below uses those
two periods as the cutover — the same reference case ``model.regime_reader`` (mvc-service-
native-db, blueprintx#289) proves against, so this shared-seam copy is checked against the
same real-world evidence rather than an invented one.
"""

import pytest

from filings_rfb._internal.utils.regime_adapter import RegimeBoundAdapter
from filings_rfb._internal.utils.regime_registry import RegimeRegistry
from filings_rfb._internal.utils.regime_window import RegimeWindow
from filings_rfb._internal.utils.spec_gap_registry import SpecGapRegistry


@pytest.fixture
def cls_registry() -> RegimeRegistry:
    """Build the two-regime registry from the issue's measured cutover (202311 / 202312).

    Returns
    -------
    RegimeRegistry
        A registry with the legacy ``cnpj_keyed`` regime (closed at ``202311``) and the
        current ``cnpj_classe_keyed`` regime (open from ``202312``).
    """
    return RegimeRegistry(
        [
            RegimeWindow(str_name="cnpj_keyed", int_period_start=None, int_period_end=202311),
            RegimeWindow(
                str_name="cnpj_classe_keyed", int_period_start=202312, int_period_end=None
            ),
        ]
    )


def test_window_covers_period_at_its_closed_end(cls_registry: RegimeRegistry) -> None:
    """The legacy window covers its own last published period, 202311.

    Parameters
    ----------
    cls_registry : RegimeRegistry
        The two-regime fixture registry.

    Returns
    -------
    None
    """
    assert cls_registry.resolve(202311).str_name == "cnpj_keyed"


def test_window_covers_period_at_the_new_regimes_start(cls_registry: RegimeRegistry) -> None:
    """The current window covers the first period published under the new schema, 202312.

    Parameters
    ----------
    cls_registry : RegimeRegistry
        The two-regime fixture registry.

    Returns
    -------
    None
    """
    assert cls_registry.resolve(202312).str_name == "cnpj_classe_keyed"


def test_default_period_for_closed_regime_returns_its_last_covered_period(
    cls_registry: RegimeRegistry,
) -> None:
    """A closed regime's default is its own newest covered period, not wall-clock "today".

    Parameters
    ----------
    cls_registry : RegimeRegistry
        The two-regime fixture registry.

    Returns
    -------
    None
    """
    assert cls_registry.default_period("cnpj_keyed") == 202311


def test_default_period_for_open_regime_raises(cls_registry: RegimeRegistry) -> None:
    """An open regime has no closed-regime default — it is the caller's concern.

    Parameters
    ----------
    cls_registry : RegimeRegistry
        The two-regime fixture registry.

    Returns
    -------
    None
    """
    with pytest.raises(ValueError, match="open"):
        cls_registry.default_period("cnpj_classe_keyed")


def test_regime_window_rejects_a_backwards_range() -> None:
    """A window whose start is after its end is refused at construction.

    Returns
    -------
    None
    """
    with pytest.raises(ValueError, match="after period end"):
        RegimeWindow(str_name="bad", int_period_start=202412, int_period_end=202401)


def test_adapter_bound_to_the_right_regime_accepts_its_own_period(
    cls_registry: RegimeRegistry,
) -> None:
    """RIGHT direction: an adapter bound to the regime that owns the period succeeds.

    Parameters
    ----------
    cls_registry : RegimeRegistry
        The two-regime fixture registry.

    Returns
    -------
    None
    """
    cls_adapter = RegimeBoundAdapter(cls_registry, "cnpj_classe_keyed", int_period=202312)
    assert cls_adapter.cls_window.str_name == "cnpj_classe_keyed"


def test_adapter_bound_to_the_wrong_regime_refuses_naming_the_sibling(
    cls_registry: RegimeRegistry,
) -> None:
    """WRONG direction: an adapter bound to the sibling regime refuses, naming the owner.

    This is the should-fail witness the pattern exists for: deriving 202312 from the legacy
    ``cnpj_keyed`` adapter would be right about 105 of 106 columns and silently wrong about
    the one that changed. The constructor refuses before any read happens.

    Parameters
    ----------
    cls_registry : RegimeRegistry
        The two-regime fixture registry.

    Returns
    -------
    None
    """
    with pytest.raises(ValueError, match="cnpj_classe_keyed"):
        RegimeBoundAdapter(cls_registry, "cnpj_keyed", int_period=202312)


def test_adapter_with_no_period_defaults_to_its_regimes_last_covered_period(
    cls_registry: RegimeRegistry,
) -> None:
    """A no-args adapter for a CLOSED regime resolves to that regime's own last period.

    Parameters
    ----------
    cls_registry : RegimeRegistry
        The two-regime fixture registry.

    Returns
    -------
    None
    """
    cls_adapter = RegimeBoundAdapter(cls_registry, "cnpj_keyed")
    assert cls_adapter.int_period == 202311


def test_unlisted_regime_has_no_known_gaps() -> None:
    """A regime absent from the registry reports every column as unexplained.

    Returns
    -------
    None
    """
    cls_registry = SpecGapRegistry({})
    assert cls_registry.is_known_gap("cnpj_keyed", "TP_FUNDO_CLASSE") is False


def test_registered_gap_is_recognised() -> None:
    """A ``(regime, column)`` pair registered as a known gap reports as known.

    Returns
    -------
    None
    """
    cls_registry = SpecGapRegistry({"cnpj_keyed": frozenset({"TP_FUNDO_CLASSE"})})
    assert cls_registry.is_known_gap("cnpj_keyed", "TP_FUNDO_CLASSE") is True


def test_unexplained_suppresses_only_the_registered_gap() -> None:
    """A narrow registry entry suppresses exactly one column — every other still surfaces.

    This is "the adapter's other oracle still running": registering ``TP_FUNDO_CLASSE`` as a
    known gap for ``cnpj_keyed`` must not also silence a genuinely new, unregistered mismatch
    (``UNEXPECTED_COLUMN``) reported in the same comparison.

    Returns
    -------
    None
    """
    cls_registry = SpecGapRegistry({"cnpj_keyed": frozenset({"TP_FUNDO_CLASSE"})})
    set_reported = frozenset({"TP_FUNDO_CLASSE", "UNEXPECTED_COLUMN"})
    assert cls_registry.unexplained("cnpj_keyed", set_reported) == frozenset({"UNEXPECTED_COLUMN"})


def test_overlapping_windows_are_rejected_at_construction() -> None:
    """Two windows covering a common period make resolve() order-dependent."""
    with pytest.raises(ValueError, match="overlap"):
        RegimeRegistry(
            [
                RegimeWindow(
                    str_name="a",
                    int_period_start=202301,
                    int_period_end=202306,
                ),
                RegimeWindow(
                    str_name="b",
                    int_period_start=202306,
                    int_period_end=202312,
                ),
            ]
        )


def test_repeated_regime_names_are_rejected_at_construction() -> None:
    """Two windows under one name make the registry's own lookups ambiguous."""
    with pytest.raises(ValueError, match="unique"):
        RegimeRegistry(
            [
                RegimeWindow(
                    str_name="dup",
                    int_period_start=202301,
                    int_period_end=202306,
                ),
                RegimeWindow(
                    str_name="dup",
                    int_period_start=202307,
                    int_period_end=202312,
                ),
            ]
        )


def test_adjacent_windows_that_do_not_overlap_are_accepted() -> None:
    """The correct case must still build, or the check fires on valid registries."""
    cls_built = RegimeRegistry(
        [
            RegimeWindow(
                str_name="old",
                int_period_start=None,
                int_period_end=202311,
            ),
            RegimeWindow(
                str_name="new",
                int_period_start=202312,
                int_period_end=None,
            ),
        ]
    )
    assert len(cls_built.list_windows) == 2


def test_covers_rejects_a_month_outside_01_12() -> None:
    """An open window would otherwise report month 13 as covered."""
    cls_open = RegimeWindow(
        str_name="open",
        int_period_start=None,
        int_period_end=None,
    )
    with pytest.raises(ValueError, match="month 01-12"):
        cls_open.covers(202313)


def test_covers_still_accepts_a_valid_period_on_an_open_window() -> None:
    """The guard must not reject the case the window exists to serve."""
    cls_open = RegimeWindow(
        str_name="open",
        int_period_start=None,
        int_period_end=None,
    )
    assert cls_open.covers(202312) is True


def test_a_later_append_to_the_callers_list_cannot_reach_the_registry() -> None:
    """Storing the caller's list by reference lets an append bypass the ambiguity check."""
    list_windows = [RegimeWindow(str_name="old", int_period_start=None, int_period_end=202311)]
    cls_registry = RegimeRegistry(list_windows)

    list_windows.append(
        RegimeWindow(str_name="overlap", int_period_start=None, int_period_end=202312)
    )

    assert len(cls_registry.list_windows) == 1


def test_the_stored_windows_cannot_be_appended_to() -> None:
    """The second path in: mutating the attribute itself."""
    cls_registry = RegimeRegistry(
        [RegimeWindow(str_name="old", int_period_start=None, int_period_end=202311)]
    )

    with pytest.raises(AttributeError):
        cls_registry.list_windows.append(  # type: ignore[attr-defined]
            RegimeWindow(str_name="x", int_period_start=None, int_period_end=None)
        )
