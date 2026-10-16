"""`contexer demo`: the zero-setup first run."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from contexer.cli import app
from contexer.contract import ContractStore
from contexer.demo import DEMO_ROOT, create_demo_project

FIXTURE = Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "todo"


def test_bundled_demo_matches_the_benchmark_fixture() -> None:
    """The demo is the benchmark's todo app; keep them from drifting apart."""
    for name in ("index.html", "style.css"):
        assert (DEMO_ROOT / name).read_bytes() == (FIXTURE / "app" / name).read_bytes()
    assert (DEMO_ROOT / "app.fixed.js").read_bytes() == (FIXTURE / "app" / "app.js").read_bytes()
    assert (DEMO_ROOT / "app.js").read_bytes() == (FIXTURE / "bugs" / "complete-throws" / "app.js").read_bytes()
    assert (DEMO_ROOT / "contract.json").read_bytes() == (
        FIXTURE / "app" / ".contexer" / "contracts" / "todo-basics.json"
    ).read_bytes()


def test_create_demo_project_installs_an_approved_contract(tmp_path: Path) -> None:
    project = create_demo_project(tmp_path / "demo")
    assert ContractStore(project).load("todo-basics").status == "approved"
    with pytest.raises(FileExistsError):
        create_demo_project(project)


def test_demo_catches_the_bug_then_fix_passes(tmp_path: Path) -> None:
    runner = CliRunner()
    caught = runner.invoke(app, ["demo", "--dir", str(tmp_path / "a")])
    assert caught.exit_code == 1, caught.output
    assert "refesh is not defined" in caught.output

    fixed = runner.invoke(app, ["demo", "--dir", str(tmp_path / "b"), "--fix"])
    assert fixed.exit_code == 0, fixed.output
    assert "SIMULATED" in fixed.output
