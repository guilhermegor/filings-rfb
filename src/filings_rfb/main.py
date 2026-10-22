"""Library entry point.

Rename or split this module as the library's public API grows.
"""

from ._internal.utils.typing import type_checker


@type_checker
def main() -> None:
    """Print a greeting — the placeholder entry point for a new library."""
    print("Hello from lib-minimal!")
