# Dynamic version stub (#51)

## Done

- [x] `pyproject.toml` back to the `0.0.0` stub; comment block moved to docs/contributing.md
- [x] `bin/check_dynamic_version_stub.py` gate in pre-commit, `poe lint` and CI, with tests
- [x] Comment-budget baseline for `pyproject.toml` lowered from 4 to 1
- [x] Review: Commitizen reads tags (`version_provider = "scm"`), releases start only from
  `workflow_dispatch`, `importlib.metadata` reports the stub in a dev venv

## Open

- [ ] Merge PR #54
- [ ] Backport the gate to blueprintx `templates/python-common/`
