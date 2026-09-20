"""Enforce one typing policy, including actual source coverage and comment tokens.

Independent implementation informed by Perevoditarr's AGPL-3.0 checker at
934638771acf2aa93d1fe20c369ab60558f648bc; see docs/typing-policy.md.
"""

import ast
import io
import re
import sys
import tokenize
import tomllib
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
KEYS = {"pythonVersion", "typeCheckingMode", "include"}
REQUIRED = {"src", "tests", "tools"}
GENERATED = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "build"}
INLINE = re.compile(r"# pyright: ignore\[report[A-Za-z]+\] +-- +\S.{9,}$")
DIRECTIVE = re.compile(r"#\s*(?:pyright|basedpyright)\s*:|#\s*type\s*:\s*ignore", re.I)


def inventory(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*")
        if not (set(p.relative_to(root).parts) & GENERATED) and p.is_file()
    )


def check(root: Path) -> list[str]:
    """Check a project independently of cwd; return actionable diagnostics."""
    root = root.resolve()
    errors: list[str] = []
    config = root / "pyproject.toml"

    def fail(path: Path, message: str, line: int = 1) -> None:
        errors.append(f"{path}:{line}: {message}")

    try:
        text = config.read_text()
        data = cast("dict[str, object]", tomllib.loads(text))
    except (OSError, ValueError) as exc:
        fail(config, f"cannot read valid TOML: {exc}")
        return errors
    section_line = next(
        (i for i, line in enumerate(text.splitlines(), 1) if line.strip() == "[tool.basedpyright]"),
        1,
    )
    tool = data.get("tool")
    table: object = None
    if isinstance(tool, dict):
        typed_tool = cast("dict[str, object]", tool)
        if "pyright" in typed_tool:
            fail(config, "competing [tool.pyright] is prohibited")
        table = typed_tool.get("basedpyright")
    includes: list[Path] = []
    if not isinstance(table, dict):
        fail(config, "missing [tool.basedpyright]")
    else:
        policy = cast("dict[str, object]", table)
        if set(policy) != KEYS:
            fail(config, f"expected only {sorted(KEYS)}; got {sorted(policy)}", section_line)
        for key, value in (("pythonVersion", "3.14"), ("typeCheckingMode", "recommended")):
            if policy.get(key) != value or not isinstance(policy.get(key), str):
                fail(config, f'{key} must be the string "{value}"', section_line)
        raw = policy.get("include")
        entries = cast("list[object]", raw) if isinstance(raw, list) else []
        if not isinstance(raw, list) or not entries:
            fail(config, "include must be a nonempty list of plain relative paths", section_line)
        names: set[str] = set()
        for entry in entries:
            if not isinstance(entry, str) or not re.fullmatch(
                r"[A-Za-z0-9_-][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*", entry
            ):
                fail(
                    config,
                    "include entries must be plain relative directories or .py/.pyi files (no globs)",
                    section_line,
                )
                continue
            path = root / entry
            if ".." in path.parts or not path.resolve().is_relative_to(root) or path.is_symlink():
                fail(config, f"include escapes project or is a symlink: {entry}", section_line)
                continue
            names.add(entry)
            if not path.exists():
                fail(config, f"include path does not exist: {entry}", section_line)
            elif path.is_file() and path.suffix not in {".py", ".pyi"}:
                fail(config, f"include file must be Python: {entry}", section_line)
            else:
                includes.append(path)
        if not names >= REQUIRED:
            fail(config, f"include must explicitly cover {sorted(REQUIRED)}", section_line)

    files = inventory(root)
    sources = [p for p in files if p.suffix in {".py", ".pyi"}]
    for included in includes:
        if not any(p == included or p.is_relative_to(included) for p in sources):
            fail(config, f"include has no maintained Python source: {included.relative_to(root)}")
    for source in sources:
        if source.is_symlink():
            fail(source, "maintained Python sources must not be symlinks")
        if not any(source == p or source.is_relative_to(p) for p in includes):
            fail(source, "not covered by include; explicitly add its maintained path")
        try:
            with tokenize.open(source) as handle:
                content = handle.read()
            _ = ast.parse(content, filename=str(source))
            for token in tokenize.generate_tokens(io.StringIO(content).readline):
                if token.type != tokenize.COMMENT or not DIRECTIVE.search(token.string):
                    continue
                if not INLINE.fullmatch(token.string) or not token.line[: token.start[1]].strip():
                    fail(
                        source,
                        "only inline # pyright: ignore[reportRule] -- justification is permitted",
                        token.start[0],
                    )
        except (OSError, SyntaxError, UnicodeError, tokenize.TokenError) as exc:
            fail(source, f"cannot parse/tokenize Python: {exc}")

    # The CLI searches ancestor JSON before even considering the local TOML.
    for ancestor in root.parents:
        for name in (
            "pyrightconfig.json",
            "basedpyrightconfig.json",
            ".basedpyright/baseline.json",
        ):
            if (ancestor / name).exists():
                fail(ancestor / name, "competing ancestor configuration/baseline is prohibited")
    for path in files:
        relative = path.relative_to(root)
        if (
            path.name in {"pyrightconfig.json", "basedpyrightconfig.json"}
            or ".basedpyright" in relative.parts
        ):
            fail(path, "competing typing configuration/baseline artifact is prohibited")
        if path.name == "pyproject.toml" and path != config:
            try:
                nested = cast("dict[str, object]", tomllib.loads(path.read_text()))
                nested_tool = nested.get("tool")
                if (
                    isinstance(nested_tool, dict)
                    and {"pyright", "basedpyright"} & nested_tool.keys()
                ):
                    fail(path, "nested typing configuration is prohibited")
            except (OSError, ValueError) as exc:
                fail(path, f"cannot inspect TOML: {exc}")
    return errors


def main() -> int:
    errors = check(ROOT)
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print("basedpyright policy: OK")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
