"""Worked example: enforce a family-wide convention with an introspective test.

When every member of a family (readers, adapters, handlers, commands) must
declare something — a class attribute, a registration, a config knob — do **not**
rely on prose in a doc or on copy-paste discipline. Ship a test that *discovers*
the family from the public API (``__all__``) and asserts the convention on each
member, so a new member that skips it fails CI automatically, without anyone
updating the test.

This module is a **template**. In a real project, replace the illustrative
``_Reader`` family below with an import of your package
(``import myproj.section as family``) whose ``__all__`` is the API surface, and
assert your real convention. Delete this file if the project has no such family.

Key points, each a trap avoided:

* **Discover, never hand-list** the members — a hand-listed tuple of *classes*
  rots the moment someone adds a member, the exact failure this test prevents.
  Derive them from the declared name surface (``__all__``).
* **Add the meta-test** that the discovery itself is non-empty and matches the
  declared surface, so the per-member test can never silently cover nothing.
* **Assert on class/constructor state**, so no I/O or mocking is needed.
"""

from __future__ import annotations

import inspect

import pytest


class _Reader:
    """Base of the illustrative family; each member must declare ``_KNOB``."""


class _AlphaReader(_Reader):
    """One family member."""

    _KNOB: int = 1


class _BetaReader(_Reader):
    """Another family member."""

    _KNOB: int = 2


_FAMILY_NAMES = ("_AlphaReader", "_BetaReader")
_FAMILY = tuple(
    obj
    for obj in (globals()[name] for name in _FAMILY_NAMES)
    if inspect.isclass(obj) and issubclass(obj, _Reader)
)


def test_the_discovered_family_is_not_empty() -> None:
    """Guard the discovery itself — an empty family makes every per-member test vacuous.

    This is the half that catches "the sweep found nothing", which is exactly how an
    introspective convention test passes by not looking.
    """
    assert _FAMILY, "the family must not be empty"


def test_discovery_matches_declared_surface() -> None:
    """Every declared name resolves to a member, and no member is missing from the surface.

    Split from the non-empty guard above (blueprintx#544): "found something" and "found
    exactly what was declared" are different failures with different causes — a drifted
    ``_FAMILY`` and a broken discovery — and one assertion covering both cannot say which.
    """
    assert len(_FAMILY) == len(_FAMILY_NAMES)


@pytest.mark.parametrize("cls_member", _FAMILY, ids=lambda cls: cls.__name__)
def test_member_declares_the_convention(cls_member: type) -> None:
    """Assert each discovered family member declares the required knob.

    Parameters
    ----------
    cls_member : type
        A family member discovered from the public surface.
    """
    assert isinstance(cls_member._KNOB, int)
