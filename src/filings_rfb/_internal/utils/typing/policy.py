"""Editable runtime type-checking **policy** for the beartype-backed engine.

This module externalises the *tunable* decisions that the ``validate`` adapter (the thin
beartype wrapper alongside it) applies, so a project can adjust the policy **without editing
engine internals**. beartype has no file-based config (no TOML/INI loader); its
configuration is a :class:`~beartype.BeartypeConf` built in code — this module is that
code, isolated and documented so the knobs are discoverable and safe to change.

Flip a knob below and the engine's runtime behaviour changes on the next import — nothing
in ``validate.py`` needs to change.

Knobs
-----
VIOLATION_TYPE : ⚠ **LOAD-BEARING — do not change lightly.**
    beartype's own ``BeartypeCallHintParamViolation`` is *not* a ``TypeError`` subclass.
    The scaffolded projects — and every ``pytest.raises(TypeError)`` in their tests, plus
    any caller catching ``TypeError`` — depend on violations being ``TypeError``. Keep this
    ``TypeError`` unless you are prepared to migrate every consumer.
STRICT_BOOL : bool
    PEP 484 makes ``bool`` a subtype of ``int``, so a stray ``True`` silently counts as
    ``1``. When ``True`` (default) the ``int`` hint is overridden to reject ``bool``, and
    the override reaches inside generics such as ``list[int]``. Set ``False`` to accept
    PEP 484's default.
WIDEN_INT_TO_NUMPY : bool
    When ``True`` (default) and NumPy is installed, the ``int`` hint also admits
    ``numpy.integer`` so a NumPy scalar satisfies an ``int`` annotation. Silently ignored
    on the leaner tiers that ship without NumPy.
PEP484_NUMERIC_TOWER : bool
    beartype's ``is_pep484_tower``. When ``True``, an ``int`` annotation also accepts
    ``float``/``complex`` and a ``float`` annotation accepts ``complex`` (PEP 484's numeric
    tower). ``False`` by default — the project prefers exact numeric types. A natural
    opt-in knob.
"""

from __future__ import annotations

from typing import Annotated, Any

from beartype import BeartypeConf, BeartypeHintOverrides
from beartype.vale import Is


VIOLATION_TYPE: type[Exception] = TypeError
STRICT_BOOL: bool = True
WIDEN_INT_TO_NUMPY: bool = True
PEP484_NUMERIC_TOWER: bool = False


def _int_hint(  # complexity-ok: type metaprogramming
) -> Any:
    """Build the ``int`` replacement hint from the numeric knobs.

    Returns
    -------
    Any
        Either bare ``int`` (no override needed) or an ``Annotated``/union hint that
        widens to ``numpy.integer`` and/or rejects ``bool``, per the knobs above.
    """
    int_base: Any = int
    if WIDEN_INT_TO_NUMPY:
        try:
            import numpy as np

            int_base = int | np.integer
        except ModuleNotFoundError:  # pragma: no cover - depends on the tier's deps
            int_base = int
    if STRICT_BOOL:
        return Annotated[int_base, Is[lambda obj: not isinstance(obj, bool)]]
    return int_base


def build_conf() -> BeartypeConf:
    """Assemble the project ``BeartypeConf`` from the policy knobs.

    Returns
    -------
    BeartypeConf
        The configuration the engine adapter applies to every checked call.
    """
    int_hint = _int_hint()
    if int_hint is int:
        return BeartypeConf(
            violation_type=VIOLATION_TYPE,
            is_pep484_tower=PEP484_NUMERIC_TOWER,
        )
    return BeartypeConf(
        violation_type=VIOLATION_TYPE,
        is_pep484_tower=PEP484_NUMERIC_TOWER,
        hint_overrides=BeartypeHintOverrides({int: int_hint}),
    )


CONF = build_conf()
