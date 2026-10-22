"""Narrow, named registry of expected spec-vs-regime column gaps.

Part of the per-regime adapter pattern (issue #148), the checklist item nothing else in the
pattern delivers: "a spec documenting only the current regime is not an oracle for the
historical one". A drift/oracle check that compares a closed regime's actual columns against
a metadata spec written for the CURRENT regime will report every column the two regimes
disagree on, forever — and the fix is never a blanket suppression of that comparison, because
that would also hide a genuinely new, unexpected mismatch the same check exists to catch.

:class:`SpecGapRegistry` narrows the suppression to exactly the ``(regime, column)`` pairs a
human has confirmed are an *expected* historical gap, named individually. Everything not
listed is reported as before — "the adapter's other oracle still running", in the issue's own
words: registering one known gap changes nothing about how any other column is checked.
"""

from __future__ import annotations

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


class SpecGapRegistry(metaclass=TypeChecker):
    """Look up whether a ``(regime, column)`` pair is a known, expected spec gap.

    Parameters
    ----------
    dict_known_gaps : dict of str to frozenset of str
        Regime name → the column names that regime is KNOWN to lack in the current spec.
        A regime absent from this dict has no known gaps (every mismatch is reported).
    """

    def __init__(self, dict_known_gaps: dict[str, frozenset[str]]) -> None:
        self.dict_known_gaps = dict_known_gaps

    @type_checker
    def is_known_gap(self, str_regime_name: str, str_column: str) -> bool:
        """Return whether ``str_column`` is a registered, expected gap for the regime.

        Parameters
        ----------
        str_regime_name : str
            The regime whose spec is being compared.
        str_column : str
            The column name the comparison reported as missing from the spec.

        Returns
        -------
        bool
            ``True`` only when this exact pair was registered — never for an unlisted
            column, however similar, and never for an unlisted regime.
        """
        return str_column in self.dict_known_gaps.get(str_regime_name, frozenset())

    @type_checker
    def unexplained(  # complexity-ok: filtering by membership is the narrowing itself
        self, str_regime_name: str, set_reported_columns: frozenset[str]
    ) -> frozenset[str]:
        """Narrow a reported set of "not in spec" columns to the genuinely unexplained ones.

        This is the seam that keeps the oracle running: pass it every column a drift/oracle
        check flagged for the regime, and only the ones NOT covered by a registered gap come
        back — so a caller can suppress the known gaps while still failing on anything new.

        Parameters
        ----------
        str_regime_name : str
            The regime the columns were reported against.
        set_reported_columns : frozenset of str
            Columns a comparison reported as missing from the spec.

        Returns
        -------
        frozenset of str
            The subset of ``set_reported_columns`` with no registered gap entry — empty
            when every reported column is an expected, registered gap.
        """
        return frozenset(
            str_column
            for str_column in set_reported_columns
            if not self.is_known_gap(str_regime_name, str_column)
        )
