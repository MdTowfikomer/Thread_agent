import os
import sys
import zipfile
import tempfile
import subprocess
from pathlib import Path
from scripts.package_quaxly import package_quaxly

def test_quaxly_package_smoke_test(tmp_path):
    """
    Smoke test for the Quaxly deployment package:
    1. Builds the deployment archive.
    2. Unpacks it to pytest tmp_path.
    3. Verifies required runtime files are present and forbidden files are excluded.
    4. Executes --preflight from within the extracted artifact to confirm standalone execution.
    """
    zip_path = package_quaxly()
    assert zip_path.exists(), "Quaxly deployment package zip must exist"
    assert zip_path.stat().st_size > 0, "Package zip must not be empty"

    temp_path = Path(tmp_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(temp_path)

        # 1. Required files verification
        assert (temp_path / "Dockerfile").exists(), "Dockerfile missing from package"
        assert (temp_path / "backend" / "requirements.txt").exists(), "backend/requirements.txt missing from package"
        assert (temp_path / "backend" / "app" / "channels" / "run_gateway.py").exists(), "run_gateway.py missing"
        assert (temp_path / "backend" / "app" / "channels" / "gateway.py").exists(), "gateway.py missing"

        # 2. Forbidden files exclusion check
        forbidden_names = [".env", ".env.local", "tests", "frontend", "ARCHITECTURE_AND_DEPLOYMENT.md"]
        for root, dirs, files in os.walk(temp_path):
            for name in dirs + files:
                for f_name in forbidden_names:
                    assert name != f_name and not name.startswith(".env"), f"Forbidden file '{name}' found in deployment package!"

        # 3. Standalone --preflight execution check from extracted artifact
        backend_dir = temp_path / "backend"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(backend_dir)
        env["DISCORD_BOT_TOKEN"] = "mock_token_for_preflight_smoke_check"
        env["SUPABASE_DB_URL"] = "postgresql://mock:mock@localhost:5432/mock"
        env["GEMINI_API_KEY"] = "mock_gemini_key_smoke_test"
        env["THREAD_MOCK_DB_PREFLIGHT"] = "1"
        # Ensure minimized secrets: THREAD_JWT_SECRET and SUPABASE_SERVICE_ROLE_KEY absent
        env.pop("THREAD_JWT_SECRET", None)
        env.pop("SUPABASE_SERVICE_ROLE_KEY", None)

        cmd = [sys.executable, "-m", "app.channels.run_gateway", "--preflight"]
        proc = subprocess.run(cmd, cwd=backend_dir, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")

        assert proc.returncode == 0, f"Standalone preflight failed with exit code {proc.returncode}.\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
        assert "[RESULT] PREFLIGHT PASSED" in proc.stdout
