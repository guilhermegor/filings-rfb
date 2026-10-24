"""Smoke test: the runtime type-checking engine resolves in the wheel layout."""

import pytest

from filings_rfb._internal.utils.typing import TypeChecker, type_checker


class _Sample(metaclass=TypeChecker):
    """Exercise the metaclass after the ``_internal`` import rewrite."""

    @staticmethod
    def doubled(x: int) -> int:
        """Return ``x`` doubled.

        Parameters
        ----------
        x : int
            A number.

        Returns
        -------
        int
            ``x * 2``.
        """
        return x * 2


def test_engine_imports_and_enforces_after_rewrite() -> None:
    """The rewritten engine imports and rejects a wrong-typed argument."""
    # one-assert-ok: one positive call and one rejection are the two halves of one behaviour
    assert _Sample.doubled(5) == 10
    with pytest.raises(TypeError):
        _Sample.doubled("five")


@type_checker
def _add(a: int, b: int) -> int:
    """Add two ints — the decorated subject, defined at MODULE level.

    Nested inside the test it charged the test 1 for the nested ``def`` (tests/ is capped at
    complexity 1, ``bin/check_complexity.sh``) while adding nothing: the decorator is applied
    at definition time either way.

    Parameters
    ----------
    a : int
        First addend.
    b : int
        Second addend.

    Returns
    -------
    int
        The sum.
    """
    return a + b


def test_decorator_rejects_wrong_type() -> None:
    """The decorator validates a standalone function's arguments."""
    # one-assert-ok: one positive call and one rejection are the two halves of one behaviour
    assert _add(1, 2) == 3
    with pytest.raises(TypeError):
        _add(1, "two")
