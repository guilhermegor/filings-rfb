"""Reference data contract — copy this per real input source, then delete the example.

Declares the columns the file must carry (``tuple_required``) and the columns that must hold
at least one valid CNPJ (``tuple_cnpj_cols``). The model/controller passes this instance to
``utils.tabular_reader.read_table`` / ``read_query``, which raises ``ContractError`` on any
violation before types are applied.

⚠️ Before copying this file for a real source, **confirm which document is the contract and
get the owner's sign-off** — writing a reader against the wrong spec produces a file that
parses cleanly and carries the wrong columns, which no test here can catch. The reasoning is
in BlueprintX's ``templates/python-common/src/config/contracts/CLAUDE.md`` (upstream; not
copied into generated projects — blueprintx#325).
"""

from __future__ import annotations

from filings_rfb._internal.utils.tabular_reader import FileContract


EXAMPLE_SOURCE = FileContract(
    "Example Source",
    "example_source",
    ("code", "amount"),
    (),
)
