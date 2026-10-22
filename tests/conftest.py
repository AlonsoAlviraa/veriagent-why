import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["SAMPLE_MODE"] = "true"
os.environ.setdefault("EMBED_PROVIDER", "hash")  # tests never call a remote embedder unless a test opts in with a mock
import tempfile
# Test runs write their traces/memos to a throwaway dir, never to the repo's logs/.
os.environ["VA_LOG_DIR"] = tempfile.mkdtemp(prefix="va-test-logs-")
