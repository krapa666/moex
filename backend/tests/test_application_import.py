import os
import subprocess
import sys
from pathlib import Path


def test_application_imports_in_clean_python_process():
    backend_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(backend_dir)
    if existing_pythonpath:
        env["PYTHONPATH"] += os.pathsep + existing_pythonpath

    result = subprocess.run(
        [sys.executable, "-c", "import app.application"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
