from typing import TYPE_CHECKING

import pytest

from tools.check_basedpyright_config import check

if TYPE_CHECKING:
    from pathlib import Path

POLICY = """[tool.basedpyright]
pythonVersion = "3.14"
typeCheckingMode = "recommended"
include = ["src", "tests", "tools"]
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    for name in ("src", "tests", "tools"):
        (tmp_path / name).mkdir()
        _ = (tmp_path / name / "sample.py").write_text("value = 1\n")
    _ = (tmp_path / "pyproject.toml").write_text(POLICY)
    return tmp_path


def test_valid(project: Path) -> None:
    assert check(project) == []


@pytest.mark.parametrize(
    "change",
    [
        POLICY.replace('pythonVersion = "3.14"\n', ""),
        POLICY.replace('"3.14"', '"3.13"'),
        POLICY.replace('"3.14"', "3.14"),
        POLICY.replace('"recommended"', "false"),
        POLICY.replace('["src", "tests", "tools"]', '"src"'),
        POLICY.replace('"src",', "false,"),
        POLICY.replace('"src",', '"src/**",'),
        POLICY.replace('"src",', '".",'),
        POLICY + "failOnWarnings = true\n",
        POLICY + 'reportMissingTypeStubs = "warning"\n',
        POLICY + "[tool.basedpyright.extra]\nvalue = true\n",
        POLICY + "[tool.pyright]\n",
        "[tool.other]\n",
        "invalid = [",
    ],
)
def test_invalid_config(project: Path, change: str) -> None:
    _ = (project / "pyproject.toml").write_text(change)
    assert check(project)


@pytest.mark.parametrize("path", ["extra.py", "extra.pyi", "new_package/module.py"])
def test_uncovered_source(project: Path, path: str) -> None:
    target = project / path
    target.parent.mkdir(exist_ok=True)
    _ = target.write_text("value: int\n")
    assert any("not covered" in e for e in check(project))


@pytest.mark.parametrize(
    "path",
    [
        "pyrightconfig.json",
        "nested/pyrightconfig.json",
        ".basedpyright/baseline.json",
        "nested/.basedpyright/baseline.json",
        "basedpyrightconfig.json",
    ],
)
def test_competing_files(project: Path, path: str) -> None:
    target = project / path
    target.parent.mkdir(parents=True, exist_ok=True)
    _ = target.write_text("{}")
    assert check(project)


def test_ancestor_json(project: Path) -> None:
    child = project / "child"
    child.mkdir()
    _ = (child / "pyproject.toml").write_text(POLICY)
    _ = (project / "pyrightconfig.json").write_text("{}")
    assert any("ancestor" in e for e in check(child))


def test_nested_toml(project: Path) -> None:
    _ = (project / "src/pyproject.toml").write_text("[tool.pyright]\n")
    assert check(project)


@pytest.mark.parametrize("suffix", ["py", "pyi"])
@pytest.mark.parametrize(
    "comment",
    [
        "# pyright: ignore",
        "# pyright: ignore[reportAny]",
        "# pyright: reportAny=false",
        "# basedpyright: ignore",
        "# type: ignore",
    ],
)
def test_trailing_directives(project: Path, suffix: str, comment: str) -> None:
    _ = (project / "src" / f"bad.{suffix}").write_text(f"value = 1  {comment}\n")
    assert any("only inline" in e for e in check(project))


def test_justified_inline_and_strings(project: Path) -> None:
    _ = (project / "src/sample.py").write_text(
        'value = 1  # pyright: ignore[reportAny] -- untyped external call\nexample = "# pyright: ignore"\n"""# type: ignore"""\n'
    )
    assert check(project) == []


def test_standalone_exception(project: Path) -> None:
    _ = (project / "src/sample.py").write_text(
        "# pyright: ignore[reportAny] -- untyped external call\n"
    )
    assert check(project)


def test_parse_failure(project: Path) -> None:
    _ = (project / "src/sample.py").write_text('value = """')
    assert check(project)


def test_missing_and_empty_paths(project: Path) -> None:
    (project / "src/sample.py").unlink()
    assert check(project)
    (project / "src").rmdir()
    assert check(project)


def test_missing_toml(project: Path) -> None:
    (project / "pyproject.toml").unlink()
    assert check(project)


def test_explicit_file_include_and_stub_comments(project: Path) -> None:
    _ = (project / "extra.pyi").write_text("value: int\n")
    _ = (project / "pyproject.toml").write_text(POLICY.replace('"tools"]', '"tools", "extra.pyi"]'))
    assert check(project) == []
    _ = (project / "extra.pyi").write_text("value: int  # pyright: ignore\n")
    assert check(project)
