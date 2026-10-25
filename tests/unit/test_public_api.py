"""Unit tests for the package's public API surface."""

import filings_rfb


def test_public_api_is_exactly_the_readers() -> None:
    """``__all__`` lists the readers and their helpers, and no scaffold placeholder.

    The lib-minimal scaffold shipped a ``main()`` hello-world exported from ``__all__``; a
    name added or dropped here is a public-API change and must be deliberate.
    """
    set_expected = {
        "CNPJ_LOOKUP_NAMES",
        "__version__",
        "export_companies_parquet",
        "read_companies",
        "read_establishments",
        "read_lookup",
        "read_partners",
        "read_simples",
    }
    assert set(filings_rfb.__all__) == set_expected
