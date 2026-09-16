"""
Discloud Deployment Package Builder for Thread Discord Gateway Worker.

Prepares a standalone, production-ready Discloud deployment bundle and zip archive.
Strictly packages:
  - backend/app (runtime modules only, no caches or tests)
  - backend/requirements.txt
  - backend/discloud.config
  - backend/.discloudignore
  - backend/main.py
Guarantees:
  - Does NOT start Uvicorn or FastAPI.
  - Zero secrets or .env files included in package or archive.
  - Target entry point: python -m app.channels.run_gateway (or python main.py).
"""
import os
import shutil
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
DEPLOY_DIR = REPO_ROOT / "deploy" / "discloud"
DIST_DIR = DEPLOY_DIR / "dist"
ZIP_PATH = DIST_DIR / "thread-gateway-discloud.zip"

EXCLUDE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "tests",
    "test",
    ".git",
    "dist",
    "build",
}

EXCLUDE_FILES = {
    ".env",
    ".env.production",
    ".env.local",
    "pytest.ini",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".log",
    ".sqlite",
    ".sqlite3",
    ".zip",
}


def clean_and_prepare():
    if DEPLOY_DIR.exists():
        for item in DEPLOY_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)


def copy_runtime_files():
    # 1. Copy root deployment configs
    shutil.copy2(BACKEND_DIR / "discloud.config", DEPLOY_DIR / "discloud.config")
    shutil.copy2(BACKEND_DIR / ".discloudignore", DEPLOY_DIR / ".discloudignore")
    shutil.copy2(BACKEND_DIR / "main.py", DEPLOY_DIR / "main.py")
    shutil.copy2(BACKEND_DIR / "requirements.txt", DEPLOY_DIR / "requirements.txt")

    # 2. Copy backend/app tree selectively
    target_app_dir = DEPLOY_DIR / "app"
    source_app_dir = BACKEND_DIR / "app"

    for root, dirs, files in os.walk(source_app_dir):
        # In-place modify dirs to skip excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        rel_path = Path(root).relative_to(source_app_dir)
        dest_dir = target_app_dir / rel_path
        dest_dir.mkdir(parents=True, exist_ok=True)

        for file in files:
            if file in EXCLUDE_FILES or any(file.endswith(ext) for ext in EXCLUDE_EXTENSIONS):
                continue
            src_file = Path(root) / file
            dest_file = dest_dir / file
            shutil.copy2(src_file, dest_file)


def create_zip():
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(DEPLOY_DIR):
            # Do not zip the dist directory itself
            if "dist" in Path(root).parts:
                continue
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and d != "dist"]

            for file in files:
                if file in EXCLUDE_FILES or any(file.endswith(ext) for ext in EXCLUDE_EXTENSIONS):
                    continue
                file_path = Path(root) / file
                arcname = file_path.relative_to(DEPLOY_DIR)
                zf.write(file_path, arcname)

    size_kb = ZIP_PATH.stat().st_size / 1024
    print(f"[Discloud Package] Successfully created {ZIP_PATH} ({size_kb:.2f} KB)")


def main():
    print("[Discloud Package] Cleaning and preparing bundle directory...")
    clean_and_prepare()
    print("[Discloud Package] Copying runtime files (backend/app, requirements, discloud.config)...")
    copy_runtime_files()
    print("[Discloud Package] Creating zip archive for Discloud dashboard upload...")
    create_zip()
    print("[Discloud Package] Deployment package ready at deploy/discloud/")


if __name__ == "__main__":
    main()
