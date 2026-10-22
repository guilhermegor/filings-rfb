"""Core type-validation engine: ``validate_type`` and its method wrapper.

Backed by `beartype <https://github.com/beartype/beartype>`_ — a constant-time,
PEP-compliant runtime type checker — rather than a hand-rolled ``isinstance``
walker. beartype validates far more than the previous implementation (nested
generics, ``dict``/``tuple``/``set`` values, return types, ``TypeVar``), so the
seam gets deeper checking for less code.

This module is the **thin adapter**: it applies the project's
:class:`~beartype.BeartypeConf` to beartype's primitives. The *policy* that
``CONF`` encodes — violations raising ``TypeError``, ``bool`` rejected where
``int`` is annotated, NumPy-int widening, the PEP 484 numeric tower — lives in
the ``policy`` module alongside this one, a documented, editable seam. Tune the
policy there; do not bury decisions in this adapter.

.. note::
   **Container checking is sampled, not exhaustive.** beartype's default
   ``BeartypeStrategy.O1`` type-checks a *single pseudo-randomly chosen item*
   per container per call — that constant-time guarantee is the whole point of
   the library. A bad element in a long list is therefore caught
   probabilistically (~``1/len`` per call), where the previous hand-rolled
   engine walked every element of a ``list[...]``. In exchange, containers the
   old engine never inspected at all (``dict``/``tuple``/``set`` values, nested
   generics) are now checked, along with return types. Do not rely on a single
   call to reject a malformed long container.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from beartype import beartype
from beartype.door import die_if_unbearable

from filings_rfb._internal.utils.typing.policy import CONF


_type_check = beartype(conf=CONF)


def validate_type(value: Any, expected_type: Any, param_name: str) -> None:
    """Raise ``TypeError`` when ``value`` does not satisfy ``expected_type``.

    Parameters
    ----------
    value : Any
        Value to validate.
    expected_type : Any
        Annotation to check against.
    param_name : str
        Parameter name shown in the error message.

    Raises
    ------
    TypeError
        When the value does not match the expected type.
    """
    die_if_unbearable(value, expected_type, conf=CONF, exception_prefix=f"{param_name} ")


def create_type_checked_method(original_method: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap ``original_method`` so each call validates its argument types.

    Parameters
    ----------
    original_method : Callable[..., Any]
        Function or method to wrap.

    Returns
    -------
    Callable[..., Any]
        Wrapper that validates argument types before delegating.
    """
    return _type_check(original_method)
