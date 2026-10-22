"""Text normalisation for matching strings across heterogeneous sources.

Labels and names arrive from different sources with inconsistent casing, accents,
tabs and stray or doubled whitespace. :func:`normalize_text` collapses all of that
to a single canonical form so matching is robust: lower-cased (casefold), accents
stripped, internal whitespace collapsed to single spaces, and trimmed.

Typical use is normalising an environment name or a free-text key before an
allow-list membership test (e.g. ``normalize_text(ENV) in {"prod", "production"}``).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
import unicodedata


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


_RE_WHITESPACE = re.compile(r"\s+")


@type_checker
def normalize_text(str_value: str) -> str:
    """Return a canonical, accent-free, lower-cased form of ``str_value``.

    Parameters
    ----------
    str_value : str
        Raw text (may carry accents, tabs, doubled or edge whitespace).

    Returns
    -------
    str
        Lower-cased, accent-stripped text with whitespace collapsed and trimmed.
    """
    str_decomposed = unicodedata.normalize("NFKD", str(str_value))
    str_ascii = "".join(ch for ch in str_decomposed if not unicodedata.combining(ch))
    return _RE_WHITESPACE.sub(" ", str_ascii).strip().casefold()


@type_checker
def safe_str(value: object, default: str = "") -> str:
    """Stringify ``value`` without ever producing the literal ``"nan"``.

    ``str(float("nan"))`` is ``"nan"`` and ``str(None)`` is ``"None"`` — both are
    invalid-data sentinels that, once written to a cell/export, masquerade as real text
    and ship silently. This returns ``default`` for ``None`` and for any float NaN (so a
    missing numeric never becomes the four-letter string ``"nan"``); everything else is
    stringified normally and stripped.

    Parameters
    ----------
    value : object
        The value to stringify.
    default : str, optional
        Returned for ``None`` or a NaN float, by default ``""``.

    Returns
    -------
    str
        ``str(value).strip()``, or ``default`` when ``value`` is ``None``/NaN.
    """
    bool_missing = value is None or (isinstance(value, float) and value != value)  # noqa: PLR0124
    return default if bool_missing else str(value).strip()
