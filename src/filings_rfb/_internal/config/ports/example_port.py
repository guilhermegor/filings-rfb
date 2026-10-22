"""Reference behavioural port — copy this per real macro-section operation, then delete it.

In hexagonal *ports-and-adapters* terms this ABC is a **port**: it pins the single operation
that a family of concrete classes (the *adapters*) all implement, so callers can treat any
adapter polymorphically and every new variant conforms to the same shape. It is private
(``_internal``): consumers import the concrete adapters, never this port.

The port is generic over ``_T`` (the value it operates on) so an adapter narrows the type
through the type parameter — e.g. ``class CsvHandler(ExamplePort[pd.DataFrame])`` — rather than
by re-annotating the override, keeping the concrete signature Liskov-compatible. ``_T`` is
unbounded here; bind it (``TypeVar("_T", bound=BaseModel)``) when every adapter shares a base.

The leading underscore is deliberate: an adapter parameterises the port
(``ExamplePort[pd.DataFrame]``) and never imports the type variable by name, so ``_T`` is an
implementation detail of this module — the same convention the typeshed stubs use. Naming it
``T`` made it a public member this package's ``__all__`` did not export, which
``bin/check_all_exports.py`` correctly rejects (blueprintx#246).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Generic, TypeVar

from filings_rfb._internal.utils.typing import ABCTypeCheckerMeta


_T = TypeVar("_T")


class ExamplePort(Generic[_T], metaclass=ABCTypeCheckerMeta):
    """Contract for one behavioural operation shared across a macro-section's adapters.

    ``ABCTypeCheckerMeta`` gives both abstract-method enforcement (a partial adapter fails at
    instantiation) and runtime type checking of every call. Concrete adapters inherit the port
    and its metaclass — do **not** redeclare ``metaclass`` on a subclass; Python inherits it.

    Methods
    -------
    handle(item)
            Perform the port's single operation on ``item`` and return the result.
    """

    @abstractmethod
    def handle(self, item: _T) -> _T:
        """Perform the operation on ``item`` and return the result.

        Parameters
        ----------
        item : _T
            The value the concrete adapter operates on.

        Returns
        -------
        _T
            The operation's result.

        Raises
        ------
        NotImplementedError
            Always — a concrete adapter must override this method.
        """
        raise NotImplementedError
