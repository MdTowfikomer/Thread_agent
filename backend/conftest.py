import os
import sys
from pathlib import Path

# Add backend directory to sys.path so tests can import app.* from anywhere
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Decouple offline pytest suite from live network state so pytest -q runs hermetically and in seconds
if os.getenv("THREAD_RUN_LIVE_SUPABASE_TESTS") != "1":
    os.environ["SUPABASE_URL"] = ""
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
    os.environ["SUPABASE_SECRET_KEY"] = ""
    os.environ["SUPABASE_PUBLISHABLE_KEY"] = ""
    os.environ["SUPABASE_ANON_KEY"] = ""
    os.environ["SUPABASE_DB_URL"] = ""
    os.environ["DATABASE_URL"] = ""
    os.environ["THREAD_ALLOW_OFFLINE_IDENTITY"] = "1"
    os.environ["THREAD_ALLOW_OFFLINE_LEDGER"] = "1"

