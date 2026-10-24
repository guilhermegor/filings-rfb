"""filings-rfb package."""

from importlib.metadata import PackageNotFoundError, version

from .ingestion.cnpj.companies import export_companies_parquet, read_companies
from .main import main


try:
    __version__ = version("filings-rfb")
except PackageNotFoundError:  # pragma: no cover - source tree without an installed dist
    __version__ = "0.0.0"


__all__ = ["__version__", "export_companies_parquet", "main", "read_companies"]
