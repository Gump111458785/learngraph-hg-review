import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "integration/verify_framework.py"
spec = importlib.util.spec_from_file_location("verify_framework", SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.mark.parametrize("layout", ["learngraph_review", "src/learngraph_review"])
def test_overlay_is_isolated_and_never_copies_keys_or_runtime_files(tmp_path, layout):
    framework = tmp_path / "team"
    (framework / "core").mkdir(parents=True)
    (framework / "core/contracts.py").write_text("# independent test placeholder\n")
    package = framework / layout
    package.mkdir(parents=True)
    original = package / "team_adapter.py"
    original.write_text("old source\n")
    (package / "NOTICE.md").write_text("attribution retained\n")
    (framework / ".env").write_text("not-a-real-key\n")
    (framework / ".env.example").write_text("OPENAI_API_KEY=\n")
    (framework / "data/runtime").mkdir(parents=True)
    (framework / "data/runtime/session.sqlite").write_bytes(b"private fixture")
    (framework / "outputs").mkdir()
    (framework / "outputs/private.txt").write_text("private fixture")
    destination = tmp_path / "check"
    result = verifier.prepare(framework, destination)
    assert original.read_text() == "old source\n"
    assert "def project_root" in (result / layout / "team_adapter.py").read_text()
    assert (result / layout / "NOTICE.md").read_text() == "attribution retained\n"
    assert not (result / ".env").exists()
    assert not (result / "data/runtime").exists()
    assert not (result / "outputs").exists()
    assert (result / ".env.example").exists()
    with pytest.raises(ValueError, match="已存在"):
        verifier.prepare(framework, destination)


def test_verifier_rejects_duplicate_runtime_packages(tmp_path):
    framework = tmp_path / "team"
    (framework / "core").mkdir(parents=True)
    (framework / "core/contracts.py").write_text("# placeholder\n")
    (framework / "learngraph_review").mkdir()
    (framework / "src/learngraph_review").mkdir(parents=True)
    with pytest.raises(ValueError, match="仅存在一份"):
        verifier.prepare(framework, tmp_path / "check")


def test_verifier_rejects_output_inside_team_checkout(tmp_path):
    framework = tmp_path / "team"
    (framework / "core").mkdir(parents=True)
    (framework / "core/contracts.py").write_text("# placeholder\n")
    with pytest.raises(ValueError, match="工程外"):
        verifier.prepare(framework, framework / "outputs/check")


def test_verifier_keeps_virtualenv_interpreter_path(monkeypatch, tmp_path):
    import subprocess

    framework = tmp_path / "team"
    (framework / "core").mkdir(parents=True)
    (framework / "core/contracts.py").write_text("# placeholder\n")
    (framework / "learngraph_review").mkdir()
    executable = tmp_path / "venv/bin/python"
    executable.parent.mkdir(parents=True)
    executable.symlink_to(Path(__import__("sys").executable).resolve())
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(verifier.subprocess, "run", run)
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    result = verifier.main(
        [
            "--framework",
            str(framework),
            "--out",
            str(tmp_path / "check"),
            "--python",
            str(executable),
        ]
    )
    assert result == 0
    assert calls[0][0][0] == str(executable)  # Resolving this symlink would lose venv packages.
    assert "OPENAI_API_KEY" not in calls[0][1]["env"]
    assert calls[0][1]["env"]["PYTHON_DOTENV_DISABLED"] == "1"
