"""One schema regime's period coverage — shared, layout-agnostic value object.

Part of the per-regime adapter pattern (issue #148): a published series can change its
column set **mid-series**, under one unchanged filename pattern — each contract pinned to
its own published header, never derived from a sibling's. This value object names the
window of periods one such regime covers.

Mirrors the vocabulary of ``model.regime_window.RegimeWindow`` (mvc-service-native-db,
blueprintx#289), so a consumer that already knows that shape recognises this one — but this
copy lives in the shared ``utils/`` seam (``src/utils/`` in MVC, ``src/chassis/`` in DDD) so
any Python skeleton can adopt the pattern from one source, not just the tier it first shipped
in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TypeVar

    _F = TypeVar("_F", bound=Callable[..., object])

    def type_checker(fn: _F) -> _F:
        """Type-only stub — see src/utils/CLAUDE.md."""

    class TypeChecker(type):
        """Type-only stub — see src/utils/CLAUDE.md."""
else:
    try:
        from filings_rfb._internal.utils.typing import TypeChecker, type_checker
    except ModuleNotFoundError:
        from filings_rfb._internal.utils.typing import TypeChecker, type_checker


_INT_MIN_PERIOD = 190001
_INT_MAX_PERIOD = 999912
_INT_FIRST_MONTH = 1
_INT_LAST_MONTH = 12


@type_checker
def _validate_period(int_period: int | None, str_field: str) -> None:
    """Reject a bound that is not a ``YYYYMM`` period, allowing ``None`` for an open bound.

    Parameters
    ----------
    int_period : int or None
        The bound to validate. ``None`` means the window is open on that side.
    str_field : str
        The attribute name, used in the error message.

    Raises
    ------
    ValueError
        If the value is not a six-digit ``YYYYMM`` with a month in ``01``-``12``.

    Returns
    -------
    None
    """
    bool_valid = int_period is None or (
        _INT_MIN_PERIOD <= int_period <= _INT_MAX_PERIOD
        and _INT_FIRST_MONTH <= int_period % 100 <= _INT_LAST_MONTH
    )
    if not bool_valid:
        raise ValueError(f"{str_field} must be a YYYYMM period with month 01-12, got {int_period}")


@dataclass(frozen=True)
class RegimeWindow(metaclass=TypeChecker):
    """The period range one schema regime covers.

    Parameters
    ----------
    str_name : str
        The regime's name. Name it after what changed (the columns), never after a
        regulation or a guessed cutover date — only a pinned-header fixture proves either,
        and a wrong date-derived name is an assertion nothing re-checks.
    int_period_start : int | None
        First period this regime covers, ``YYYYMM``. ``None`` means no known earlier bound.
    int_period_end : int | None
        Last period this regime covers, ``YYYYMM``. ``None`` means the regime is still open
        (the currently published schema) — it has no closed-regime default (see
        :class:`utils.regime_registry.RegimeRegistry`).
    """

    str_name: str
    int_period_start: int | None
    int_period_end: int | None

    def __post_init__(self) -> None:
        """Reject bounds that are not ``YYYYMM``, or that run backwards.

        Raises
        ------
        ValueError
            If a bound is not a valid ``YYYYMM`` period, or the start is after the end.

        Returns
        -------
        None
        """
        _validate_period(self.int_period_start, "int_period_start")
        _validate_period(self.int_period_end, "int_period_end")
        bool_backwards = (
            self.int_period_start is not None
            and self.int_period_end is not None
            and self.int_period_start > self.int_period_end
        )
        if bool_backwards:
            raise ValueError(
                f"{self.str_name}: period start {self.int_period_start} is after period end "
                f"{self.int_period_end}"
            )

    def covers(  # complexity-ok: a two-sided open-bound range check is the validation itself
        self, int_period: int
    ) -> bool:
        """Return whether ``int_period`` falls inside this window.

        Parameters
        ----------
        int_period : int
            The period to check, ``YYYYMM``.

        Returns
        -------
        bool
            ``True`` when ``int_period`` is within ``[int_period_start, int_period_end]``
            (either bound may be open).
        """
        _validate_period(int_period, "int_period")
        bool_after_start = self.int_period_start is None or int_period >= self.int_period_start
        bool_before_end = self.int_period_end is None or int_period <= self.int_period_end
        return bool_after_start and bool_before_end

    @property
    def is_closed(self) -> bool:
        """Whether this regime has a known last period (superseded by a later one).

        Returns
        -------
        bool
            ``True`` when ``int_period_end`` is set.
        """
        return self.int_period_end is not None
