"""Ports — the behavioural boundary interfaces of the library (hexagonal, private).

In ports-and-adapters terms these ABCs are the **ports**: the abstract operation each
macro-section's concrete classes (the *adapters*) implement, so every variant conforms to the
same shape. They ship inside the wheel under ``_internal`` but are **not** part of the public
API — consumers import the concrete adapters, never these ports. Re-export each port here so
callers use one import: ``from <pkg>._internal.config.ports import ExamplePort``.
"""

from filings_rfb._internal.config.ports.example_port import ExamplePort


__all__ = ["ExamplePort"]
