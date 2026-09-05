import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

os.environ["PROVIDER_MODE"] = "mock"
os.environ["DATABASE_URL"] = f"sqlite:///{(BACKEND_DIR / 'data' / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(BACKEND_DIR / "data" / "uploads" / "test")
os.environ["KNOWLEDGE_DIR"] = str(BACKEND_DIR / "data" / "knowledge")
os.environ["MAX_FOLLOWUPS"] = "2"

