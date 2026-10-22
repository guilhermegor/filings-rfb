"""Brazilian identifier helpers — mask, unmask and validate CNPJ and CPF.

These are pure, stateless functions (no class — there is no state or lifecycle to
own). They are deliberately tolerant on input so they can be mapped over a whole
``pandas`` column: ``unmask_*`` strips punctuation, the spurious ``".0"`` left by a
float→str coercion, and (for CNPJ) handles the **2026 alphanumeric format** by keeping
``A-Z``/``0-9`` and only zero-padding when the value is purely numeric. ``is_valid_*``
return ``bool`` rather than raising, so a bad row never aborts a bulk transformation.

The CNPJ check digits use ASCII-48 weighting, which makes a single mod-11 routine
validate both legacy-numeric and new-alphanumeric CNPJs (a digit's value equals itself).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TypeVar

    _F = TypeVar("_F", bound=Callable[..., object])

    def type_checker(fn: _F) -> _F:
        """Type-only stub — see src/utils/CLAUDE.md."""
else:
    try:
        from filings_rfb._internal.utils.typing import type_checker
    except ModuleNotFoundError:
        from filings_rfb._internal.utils.typing import type_checker


_INT_MODULUS = 11
_INT_MIN_REMAINDER = 2

_LEN_CNPJ: int = 14
_LEN_CPF: int = 11
_ASCII_ZERO: int = ord("0")

_CNPJ_WEIGHTS_DV1: tuple[int, ...] = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_CNPJ_WEIGHTS_DV2: tuple[int, ...] = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)

_RE_FLOAT_ARTIFACT: re.Pattern[str] = re.compile(r"^\s*(\d+)\.0+\s*$")
_RE_NON_ALNUM: re.Pattern[str] = re.compile(r"[^0-9A-Za-z]")
_RE_NON_DIGIT: re.Pattern[str] = re.compile(r"\D")


@type_checker
def _strip_float_artifact(str_value: str) -> str:
    """Drop a trailing ``.0`` left by a float→str coercion; otherwise trim whitespace.

    Parameters
    ----------
    str_value : str
        Raw identifier as read from a source (CSV cell, DataFrame value, API field).

    Returns
    -------
    str
        ``str_value`` with a ``".0…"`` tail removed when it is an integer-with-float-tail,
        else the whitespace-trimmed input.
    """
    cls_match = _RE_FLOAT_ARTIFACT.match(str_value)
    if cls_match is not None:
        return cls_match.group(1)
    return str_value.strip()


@type_checker
def unmask_cnpj(str_value: str) -> str:
    """Normalise a CNPJ to its bare 14-character form (alphanumeric-aware).

    Parameters
    ----------
    str_value : str
        A CNPJ in any shape — masked, zero-stripped, or carrying a float ``.0`` tail.

    Returns
    -------
    str
        Uppercased value containing only ``A-Z``/``0-9``. Purely numeric values are
        left-zero-padded to 14; alphanumeric values are returned as-is (already 14).
        An empty input yields an empty string.
    """
    str_clean = _strip_float_artifact(str_value)
    str_clean = _RE_NON_ALNUM.sub("", str_clean).upper()
    if str_clean.isdigit():
        str_clean = str_clean.zfill(_LEN_CNPJ)
    return str_clean


@type_checker
def mask_cnpj(str_value: str) -> str:
    """Format a CNPJ as ``XX.XXX.XXX/XXXX-XX``.

    Parameters
    ----------
    str_value : str
        A CNPJ in any shape (it is unmasked first).

    Returns
    -------
    str
        The punctuated CNPJ when it normalises to 14 characters; otherwise the bare
        unmasked value (so malformed input is surfaced, not silently reformatted).
    """
    str_clean = unmask_cnpj(str_value)
    if len(str_clean) != _LEN_CNPJ:
        return str_clean
    return f"{str_clean[:2]}.{str_clean[2:5]}.{str_clean[5:8]}/{str_clean[8:12]}-{str_clean[12:]}"


@type_checker
def _cnpj_check_digit(str_base: str, tuple_weights: tuple[int, ...]) -> int:
    """Compute one CNPJ check digit via ASCII-48 mod-11 weighting.

    Parameters
    ----------
    str_base : str
        The base characters the weights apply to (12 for DV1, 13 for DV2).
    tuple_weights : tuple of int
        Mod-11 weights, paired left-to-right with ``str_base``.

    Returns
    -------
    int
        The check digit (0 when the remainder is below 2, else ``11 - remainder``).
    """
    int_sum = sum(
        (ord(str_char) - _ASCII_ZERO) * int_weight
        for str_char, int_weight in zip(str_base, tuple_weights, strict=True)
    )
    int_rest = int_sum % 11
    return 0 if int_rest < _INT_MIN_REMAINDER else _INT_MODULUS - int_rest


@type_checker
def is_valid_cnpj(str_value: str) -> bool:
    """Validate a CNPJ's two check digits (legacy numeric or 2026 alphanumeric).

    Parameters
    ----------
    str_value : str
        A CNPJ in any shape (it is unmasked first).

    Returns
    -------
    bool
        ``True`` when the value normalises to 14 characters whose last two are the
        correct numeric check digits. Repeated-character numeric values (e.g. all
        zeros) are rejected.
    """
    str_clean = unmask_cnpj(str_value)
    return (
        len(str_clean) == _LEN_CNPJ
        and str_clean[12:].isdigit()
        and not (str_clean.isdigit() and len(set(str_clean)) == 1)
        and str_clean[12:] == _cnpj_check_digits(str_clean[:12])
    )


@type_checker
def _cnpj_check_digits(str_base: str) -> str:
    """Return the two check digits for a 12-character CNPJ base.

    Parameters
    ----------
    str_base : str
        The first 12 characters of an unmasked CNPJ.

    Returns
    -------
    str
        The two check digits, concatenated.
    """
    int_dv1 = _cnpj_check_digit(str_base, _CNPJ_WEIGHTS_DV1)
    int_dv2 = _cnpj_check_digit(f"{str_base}{int_dv1}", _CNPJ_WEIGHTS_DV2)
    return f"{int_dv1}{int_dv2}"


@type_checker
def unmask_cpf(str_value: str) -> str:
    """Normalise a CPF to its bare 11-digit form.

    Parameters
    ----------
    str_value : str
        A CPF in any shape — masked, zero-stripped, or carrying a float ``.0`` tail.

    Returns
    -------
    str
        Digits only, left-zero-padded to 11 when non-empty; empty input yields ``""``.
    """
    str_clean = _strip_float_artifact(str_value)
    str_clean = _RE_NON_DIGIT.sub("", str_clean)
    if str_clean:
        str_clean = str_clean.zfill(_LEN_CPF)
    return str_clean


@type_checker
def mask_cpf(str_value: str) -> str:
    """Format a CPF as ``XXX.XXX.XXX-XX``.

    Parameters
    ----------
    str_value : str
        A CPF in any shape (it is unmasked first).

    Returns
    -------
    str
        The punctuated CPF when it normalises to 11 digits; otherwise the bare
        unmasked value.
    """
    str_clean = unmask_cpf(str_value)
    if len(str_clean) != _LEN_CPF:
        return str_clean
    return f"{str_clean[:3]}.{str_clean[3:6]}.{str_clean[6:9]}-{str_clean[9:]}"


@type_checker
def _cpf_check_digit(str_base: str, int_start_weight: int) -> int:
    """Compute one CPF check digit via descending mod-11 weighting.

    Parameters
    ----------
    str_base : str
        The base digits the weights apply to (9 for DV1, 10 for DV2).
    int_start_weight : int
        The first (largest) weight; subsequent weights descend by one.

    Returns
    -------
    int
        The check digit (0 when the remainder is below 2, else ``11 - remainder``).
    """
    int_sum = sum(
        int(str_char) * (int_start_weight - int_idx) for int_idx, str_char in enumerate(str_base)
    )
    int_rest = int_sum % 11
    return 0 if int_rest < _INT_MIN_REMAINDER else _INT_MODULUS - int_rest


@type_checker
def is_valid_cpf(str_value: str) -> bool:
    """Validate a CPF's two check digits.

    Parameters
    ----------
    str_value : str
        A CPF in any shape (it is unmasked first).

    Returns
    -------
    bool
        ``True`` when the value normalises to 11 digits whose last two are the correct
        check digits. Repeated-digit values (e.g. all ones) are rejected.
    """
    str_clean = unmask_cpf(str_value)
    return (
        len(str_clean) == _LEN_CPF
        and str_clean.isdigit()
        and len(set(str_clean)) > 1
        and str_clean[9:] == _cpf_check_digits(str_clean)
    )


@type_checker
def _cpf_check_digits(str_clean: str) -> str:
    """Return the two check digits for an 11-digit CPF.

    Parameters
    ----------
    str_clean : str
        An unmasked, 11-digit CPF.

    Returns
    -------
    str
        The two check digits, concatenated.
    """
    int_dv1 = _cpf_check_digit(str_clean[:9], 10)
    int_dv2 = _cpf_check_digit(str_clean[:10], 11)
    return f"{int_dv1}{int_dv2}"
