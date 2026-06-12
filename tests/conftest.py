"""
Shared test setup. Point DATA_DIR at a throwaway dir BEFORE server/store import so the
SQLite state never touches the repo, and keep PAPER_TRADING on.
"""
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="cryptoagent_test_"))
os.environ.setdefault("PAPER_TRADING", "true")
os.environ.setdefault("WEBHOOK_SECRET", "test-secret")
