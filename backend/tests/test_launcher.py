"""Exercise the host workflow with a fake Docker executable; no real daemon is required."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def launcher(tmp_path):
    project = tmp_path / "Project With Spaces"
    project.mkdir()
    script = project / "iniciar.sh"
    script.write_text((ROOT / "iniciar.sh").read_text())
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    docker = binary_dir / "docker"
    docker.write_text("""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CALL_LOG"
case "$*" in
  'compose version'|'info') exit 0 ;;
  'compose port app 8000') echo '127.0.0.1:8123' ;;
  'compose up '*) exit "${FAKE_START_STATUS:-0}" ;;
  'compose exec '*) exit "${FAKE_COLLECT_STATUS:-0}" ;;
  *) exit 99 ;;
esac
""")
    docker.chmod(0o755)
    log = tmp_path / "commands.log"
    env = {**os.environ, "PATH": f"{binary_dir}:{os.environ['PATH']}", "CALL_LOG": str(log)}
    return script, project, log, env


def test_launcher_starts_waits_collects_and_reuses_image(launcher):
    script, project, log, env = launcher
    result = subprocess.run(
        ["bash", str(script), "--no-browser"], env=env, capture_output=True, text=True, check=True
    )
    commands = log.read_text()
    assert "compose up --detach --wait --wait-timeout 120 app" in commands
    assert "compose exec -T app python -m collector" in commands
    assert "--build" not in commands
    assert "http://127.0.0.1:8123" in result.stdout
    assert (project / "backend" / "data").is_dir()


def test_launcher_opens_app_even_when_collection_fails(launcher):
    script, _, log, env = launcher
    env["FAKE_COLLECT_STATUS"] = "1"
    result = subprocess.run(
        ["bash", str(script), "--no-browser"], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert "aplicativo continua disponível" in result.stderr
    assert "compose exec -T app python -m collector" in log.read_text()


def test_launcher_build_and_offline_consultation_options(launcher):
    script, _, log, env = launcher
    subprocess.run(
        ["bash", str(script), "--build", "--no-browser", "--no-collect"],
        env=env,
        capture_output=True,
        check=True,
    )
    assert "--build app" in log.read_text()
    assert "compose exec" not in log.read_text()


def test_launcher_does_not_collect_if_startup_fails(launcher):
    script, _, log, env = launcher
    env["FAKE_START_STATUS"] = "1"
    result = subprocess.run(
        ["bash", str(script), "--no-browser"], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 1
    assert "Falha ao iniciar" in result.stderr
    assert "compose exec" not in log.read_text()
