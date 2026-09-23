# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Newznab adapter (Litestar + GranianPlugin + msgspec, Python 3.14) in front of the WTFNZB site.
It uses a single package, `src/wtfnzb_adapter`. Upstream is scraped HTML/XML with no documented
API, so parsers and limits are shaped by recorded evidence, not by what seems reasonable.

## Commands

Everything runs through `uv run --locked` from the repo root (`.env` is read from the cwd).

```sh
uv sync --locked                                   # first; there is no committed .venv
uv run --locked pytest                             # tests (not run by the git hooks)
uv run --locked pytest tests/test_parsing.py
uv run --locked pytest tests/test_service.py::test_rate_limit_persists_and_auth_latches
uv run --locked ruff format --check . && uv run --locked ruff check .
uv run --locked python tools/check_basedpyright_config.py && uv run --locked basedpyright
SKIP=no-commit-to-branch uv run --locked prek run --all-files   # full hook set, as CI runs it
```

- After `uv run --locked prek install`, the `no-commit-to-branch` hook rejects commits on `main`.
  `prek run --all-files` on `main` fails for the same reason. CI sets `SKIP=no-commit-to-branch`, so use that skip locally too.
- The pre-commit hooks run lock check, ruff, the typing gate and basedpyright over the whole project,
  but not pytest. Run pytest separately.
- Commit messages must follow Conventional Commits. The `commit-msg` hook enforces this.

## Typing policy (enforced by `tools/check_basedpyright_config.py`)

- `[tool.basedpyright]` must hold exactly `pythonVersion`, `typeCheckingMode`, `include`. Any other
  key, `[tool.pyright]`, `pyrightconfig.json`, or `.basedpyright/` baseline fails CI. Fix the code instead.
- Every `.py` file must sit under `src`, `tests` or `tools`. A new top-level Python dir fails the
  gate until it is added to `include`.
- The only allowed suppression is trailing and rule-specific with a justification:
  `# pyright: ignore[reportRuleName] -- reason of ten+ chars`. `# type: ignore` and standalone
  pragmas are rejected. See `docs/typing-policy.md`.
- `recommended` mode flags unused call results. Discard them as `_ = call()`, as the code does throughout.
- The code uses PEP 758 `except A, B:` without parentheses. It is valid on 3.14, so leave it as is.

## Invariants

- All upstream HTTP goes through `Upstream.request()` in `upstream.py`. It holds the lock, spacing,
  hourly/daily budget, cooldown, auth latch and byte cap. Never build another `httpx` client or call
  the site directly: that bypasses the persisted budget in `<state_dir>/budget.json`.
- Run exactly one process and one worker. `Upstream.__init__` takes an exclusive `flock` on
  `instance.lock`, so construct `Upstream` only inside the app lifespan (`app.py`). Building it at
  factory/import time causes a false "another instance" error under `litestar run`. The generic
  `.agents/rules` advice to set workers to the core count does not apply here.
- Failures raise `AdapterError(message, newznab_code, http_status)` (default 900/502). The
  controller turns it into Newznab `<error>` XML. Partial, truncated or ambiguous upstream results
  must raise, never return an empty or short success. There are no automatic retries.
- Parsers in `parsing.py` reject missing metadata (raise `AdapterError`) instead of defaulting.
  Categories come from the site's links only, never guessed from titles.
- CPU-bound parsing is off-loop via `anyio.to_thread.run_sync(parsing.fn, raw, ...)` in `service.py`.
- Budget numbers live in two places. `Settings` defaults in `config.py` (not env-configurable) feed
  `Upstream`. `session_budget.py` hard-codes `500`/`60`/`10` s and the 3-operation reserve.
  Change both together.
- Category IDs. `categories.json` stores upstream IDs. `parsing.CATEGORY_REMAP` maps them to the
  Newznab-facing IDs (8020–8060 become 108020–108060, 1090→1140, 1100→1180), and `service.collect`
  reverse-maps for RSS. `service.category_matches` treats IDs ≥100000 as children of 8000.
  Edit the remap and the JSON together.
- Secrets. `Settings` and `Credentials` override `__repr__` to redact, so keep that on any new
  secret-bearing Struct. Auth and `.env` files must be mode 0600 (code enforces it). `.env` and
  `.state/` are git-ignored.

## Tests

Tests use sanitized real upstream responses in `docs/evidence/`, accessed through the `evidence`
fixture in `tests/conftest.py`. Add a new fixture file there rather than inlining HTML. Don't edit
existing evidence files: docs cite them as recorded observations. Service/app tests stub the upstream
with `httpx.MockTransport` and inject the service into the app. From `tests/test_service.py`:

```python
def make_service(settings: Settings, handler: Callable[[httpx.Request], httpx.Response]) -> Service:
    return Service(Upstream(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler))))

@pytest.mark.anyio
async def test_...(settings: Settings, evidence: Path) -> None:
    service = make_service(settings, upstream)
    async with AsyncTestClient(create_app(settings, service)) as client: ...
```

The module's `settings` fixture sets `spacing=0`. Without it, each upstream call sleeps 10 s.

## Reference docs

- `.agents/rules/python-3_14-litestar-api.md` covers generic Litestar/msgspec/Granian conventions.
  Read it before adding handlers or Structs. Its sample `[tool.basedpyright]` (`reportMissingTypeStubs`,
  two-entry `include`) and bare `ignore[rule]` examples conflict with this repo's gate, so the repo policy wins.
  This project has no DB, Advanced Alchemy or OpenAPI.
- `docs/findings.md` and `docs/authentication-and-limits.md` record observed upstream behavior
  and limits. Read them before changing parsers, search flow, rate limits or session handling.
- `docs/project-plan.md` lists open reliability gates and what must not be advertised. Read it
  before adding capabilities to `newznab.caps()`.
