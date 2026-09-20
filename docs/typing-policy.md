# Typing policy implementation

The sole configuration is `[tool.basedpyright]` in root `pyproject.toml`, with
exactly `pythonVersion`, `typeCheckingMode`, and `include`. Warnings are failures.
All maintained Python is checked, including the checker itself. No diagnostic
suppressions are currently needed in the application or tools.

`tools/check_basedpyright_config.py` is an independent implementation informed by
[Perevoditarr's checker at 934638771acf2aa93d1fe20c369ab60558f648bc](https://github.com/engels74/perevoditarr/blob/934638771acf2aa93d1fe20c369ab60558f648bc/backend/tools/check_basedpyright_config.py).
The current source and AGPL-3.0 license were read on September 20, 2026 local time.
This repository retains its existing AGPL-3.0 license. No upstream code was copied
verbatim. The reference supplied the three-key policy and competing-config checks;
this implementation validates values/types, inventories `.py` and `.pyi`, checks
real paths, and inspects Python comment tokens and syntax.

Include entries are plain relative directory or `.py`/`.pyi` file paths, without
globs, symlinks, parent traversal or `.`. Required `src`, `tests`, and `tools`
directories must exist and contain Python. New maintained source outside included
paths causes failure until explicitly included. Known generated directories
(`.git`, `.venv`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `build`, `dist`)
are omitted; arbitrary hidden folders and Git-ignored source are not excluded.

Discovery was verified against the installed **basedpyright 1.40.1** bundle:
`dist/pyright.js`, `_getConfigOptions` around lines 87165–87265,
`_getExtendedConfigurations` around 87548, `_parsePyprojectTomlFile` around 87619,
and the ancestor search helpers around 88075–88095. For CLI invocation from the
project root, ancestor `pyrightconfig.json` is searched **before** local TOML.
Therefore the checker rejects ancestor JSON as well as nested/root JSON. A local
valid typing table prevents fallback to ancestor TOML. Competing `[tool.pyright]`
and nested typing TOML tables are rejected. The default baseline is
`.basedpyright/baseline.json`; any repository `.basedpyright` artifact is rejected,
as is an ancestor default baseline. `baselineFile`, `extends`, and all other extra
keys are rejected by the structural allowlist, including nested tables.

The fixed hook and CI commands invoke `basedpyright` from the repository root
without `--project`, `--baselinefile`, severity switches, or filename arguments.
The checker itself resolves the project root from its own location. No editor
configuration or environment variable overrides those fixed CLI arguments.

Comments are tokenized, so pragma examples in strings/docstrings are harmless.
Both standalone and trailing active directives are inspected. Only a rule-specific
inline ignore followed by `--` and a substantive short explanation is syntactically
permitted. Tests use temporary projects, so deliberately forbidden examples do not
become active bypasses in this repository. Human review must still establish that
any permitted exception concerns a genuinely untyped third-party call site.
