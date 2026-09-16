import os
import sys
import zipfile
from pathlib import Path

def package_quaxly():
    root_dir = Path(__file__).parent.parent.resolve()
    deploy_dir = root_dir / "deploy" / "quaxly"
    dist_dir = deploy_dir / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    output_zip = dist_dir / "thread-gateway-quaxly.zip"
    if output_zip.exists():
        output_zip.unlink()

    print(f"[Package Quaxly] Packaging standalone Discord Gateway worker...")
    print(f"  Source Root: {root_dir}")
    print(f"  Destination: {output_zip}")

    excluded_patterns = {
        ".env", ".env.local", ".env.production", ".env.development",
        "ARCHITECTURE_AND_DEPLOYMENT.md",
        "tests", "__pycache__", ".pytest_cache", ".git", "node_modules", "frontend"
    }

    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Add Dockerfile at root of archive
        dockerfile_path = deploy_dir / "Dockerfile"
        if dockerfile_path.exists():
            zf.write(dockerfile_path, arcname="Dockerfile")
            print("  + Added Dockerfile")

        # 2. Add backend/requirements.txt
        req_path = root_dir / "backend" / "requirements.txt"
        if req_path.exists():
            zf.write(req_path, arcname="backend/requirements.txt")
            print("  + Added backend/requirements.txt")

        # 3. Add backend/app directory
        app_dir = root_dir / "backend" / "app"
        for path in app_dir.rglob("*"):
            if any(part in excluded_patterns or part.startswith(".env") for part in path.parts):
                continue
            if path.is_file():
                arcname = path.relative_to(root_dir)
                zf.write(path, arcname=arcname)

    print(f"[Package Quaxly] Successfully created standalone archive ({output_zip.stat().st_size} bytes)")
    return output_zip

if __name__ == "__main__":
    package_quaxly()
