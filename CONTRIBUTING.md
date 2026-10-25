# Contribution Guidelines

Thank you for considering contributing to our project! Please take a moment to review these guidelines to ensure a smooth collaboration.

> **First of all, open an issue.** Every change starts with an issue in
> [GitHub Issues](../../issues), opened from the issue template, before any branch or PR. The
> branch is named after it (`<type>/<issue-number>-<slug>`), and the PR body closes it
> (`Closes #<N>`). The `branch-has-issue` check rejects a PR whose branch names no issue.

## Development Conventions

### Variable Naming Standards

We use the following standardized variable naming conventions:

| Variable        | Description |
|-----------------|-------------|
| `int_cddr`      | Integer calendar days redemption period (funding to delivery) |
| `int_wddr`      | Integer working days redemption period (funding to delivery) |
| `int_cddt`      | Integer calendar days total investment period (funding to maturity) |
| `int_wddt`      | Integer working days total investment period (funding to maturity) |
| `int_cddm`      | Integer calendar days per month (convention: 30) |
| `int_wddm`      | Integer working days per month (convention: 22) |
| `int_cddy`      | Integer calendar days per year (convention: 365) |
| `int_wddy`      | Integer working days per year (convention: 252) |
| `int_cd_bef`    | Integer calendar days before (convention: 1) |
| `int_wd_bef`    | Integer working days before (convention: 1) |
| `int_cd_aft`    | Integer calendar days after (convention: 1) |
| `int_wd_aft`    | Integer working days after (convention: 1) |
| `int_cd_cap`    | Integer calendar days capitalization |
| `int_wd_cap`    | Integer working days capitalization |
| `int_nper_cd`   | Integer number of periods (calendar days) |
| `int_nper_wd`   | Integer number of periods (working days) |
| `float_pv`      | Present value of instrument notional (negative for purchasing, positive for selling) |
| `float_fv`      | Future value of instrument notional (negative for purchasing, positive for selling) |
| `float_notional`| Priced value from contract in absolute terms |
| `float_position_value`| Accounting current market value, for taxing purposes |
| `float_acquisition_basis`| Accounting cost basis, for taxing purposes |
| `float_size`    | Size of instrument contract |
| `float_xcg`     | Exchange value for instrument pricing |
| `float_qty`     | Quantity of instruments (positive for purchasing, negative for selling) |
| `date_ref`        | Reference date |
| `date_xpt`        | Maturity date |
| `date_rdm`        | Redemption date |
| `date_start`        | Start date |
| `date_end`        | End date |
| `date_current` | Current date, for iteration puroposes|
| `int_n_smp`     | Number of samples |
| `int_max_retries` | Maximum number of retries |

## Branching Strategy

**`main` is protected — direct commits and pushes are blocked** (`no-commit-to-branch` locally,
server-side branch protection on GitHub). All changes land via a branch → Pull Request → merge
(online), or `poe new_branch` → `poe git_merge_to_main` (offline).

### Branch Naming Convention

All branches must follow the pattern: `<purpose>/<issue-number>-<branch-task>`
(for example `feat/42-user-authentication`). The `branch-has-issue` workflow rejects a
branch without the issue number, except `release/`, `dependabot/` and `renovate/`

**Available purposes:**

| Purpose         | Format                      | When to Use |
|-----------------|-----------------------------|-------------|
| Feature         | `feature/<N>-<name>` or `feat/<N>-<name>` | New functionality |
| Bugfix          | `bugfix/<N>-<description>` or `fix/<N>-<description>` | Bug resolution |
| Hotfix          | `hotfix/<N>-<description>` | Critical production fixes |
| Release         | `release/<version>` | Version preparation |
| Documentation   | `docs/<N>-<description>` | Documentation updates |
| Refactor        | `refactor/<N>-<description>` | Code improvements |
| Chore           | `chore/<N>-<description>` | Project maintenance tasks |

**Examples:**
- `feat/42-user-authentication`
- `fix/57-login-validation-issue`
- `docs/63-update-api-reference`

## Commit Message Standards

All commits must follow the [Conventional Commits](https://www.conventionalcommits.org/) specification: `<type>/<scope>`

**Available types:**

| Type       | Purpose |
|------------|---------|
| `build`    | Build system or dependency changes |
| `ci`       | CI configuration changes |
| `docs`     | Documentation updates |
| `feat`     | New features |
| `fix`      | Bug fixes |
| `perf`     | Performance improvements |
| `refactor` | Code restructuring |
| `style`    | Formatting changes |
| `test`     | Test additions/modifications |
| `chore`    | Maintenance tasks |
| `revert`   | Reverting changes |
| `bump`     | Version updates |

**Examples:**
- `feat(auth): implement OAuth2 integration`
- `fix(calculations): correct rounding errors in tax computation`
- `docs(readme): add installation instructions`

**Pre-flight before committing:** `poe check_commit_msg <file>` runs the same gitlint +
commitizen checks the `commit-msg` hook enforces, in seconds — catching a too-long title or
a wrong type before it is rediscovered after the full pre-commit gate (lint, tests, coverage)
has already run.

## Development Setup

1. **Dependency Management**:
   - Use Poetry (version specified in `requirements.txt`)
   - Avoid adding redundant libraries - check `pyproject.toml` first
   - Run `poetry install` to set up the development environment

2. **Pre-commit Hooks**:
   - Install with `poe precommit`
   - This enables automatic:
     - Code linting
     - Formatting
     - Security vulnerability scanning
     - Large file detection
     - Secret key detection

3. **Testing Framework**:
   - Maintain the standard file structure:
     - Implementation: `src/<feat_name>.py`
     - Tests: `tests/test_<feat_name>.py`
   - Run comprehensive validation with: `poe unit_tests -k <keyword>`
        - This command executes:
            - **Ruff**: Linting, formatting, and flagging deprecated Python features
            - **Codespell**: Spelling verification in comments and docstrings
            - **Automated tests**: All test cases matching the project's testing standards
   - Ensure 100% test coverage for critical components
   - Run tests locally before pushing changes

4. **Test-Driven Development**:
   - Write tests before implementation when possible
   - Include normal operations, edge cases, error conditions, type validation, and checks for examples in docstrings
   - Maintain test fixtures for complex scenarios
   - Recommended to use UNIT_TEST_TEMPLATE.md for AI generation of unit tests, in order to implement test-driven development best practices and follow project standards

5. **Test order and seed-specific failures**:
   - `pytest-randomly` shuffles test order on every run and prints the seed used, pass or
     fail — a hidden dependency between tests (a `get` test relying on state a `post` test
     left behind) fails instead of passing silently forever.
   - The seed is reported in the session header as `Using --randomly-seed=<N>`, on every
     run rather than only on failure. To reproduce an order, build the command from that
     number yourself: `pytest -p randomly --randomly-seed=<N>`.
   - **A test that fails only under a particular seed is a real defect, never flakiness to
     re-run away.** Re-running until it goes green hides the exact bug this exists to catch
     — report the seed and the failing test instead of retrying.
   - A test fixture with `scope="module"`/`"class"`/`"session"` shares its instance across
     tests, which is exactly the shape an order dependency takes. `check_fixture_scope.py`
     (a proxy, not a detector — see its module docstring) requires a written
     `# fixture-scope-ok: <reason>` comment before it accepts one.

## Pull Request Process

1. **Create an Issue First**:
   - Check existing issues on this repository's [GitHub Issues](../../issues) page
   - Open a new issue if none exists for your work

2. **Opening a PR**:
   - Fill out the PR template completely
   - Include:
     - Detailed description
     - Changes made
     - Testing performed
     - Documentation updates
     - Any technical debt created

3. **Code Review**:
   - Expect constructive feedback
   - Address all review comments
   - Update documentation as needed
   - Keep commits logically organized

4. **Merge Approval**:
   - Requires at least one approval
   - All tests must pass
   - Code coverage should not decrease
   - Documentation must be updated

## Best Practices

- **Keep branches focused** - one feature/bugfix per branch
- **Make small, frequent commits** - easier to review
- **Write descriptive commit messages** - explain why, not just what
- **Update documentation** - when adding new features
- **Follow existing patterns** - maintain consistency
- **Communicate early** - if you're stuck or need clarification

We appreciate your contributions and look forward to collaborating with you!
