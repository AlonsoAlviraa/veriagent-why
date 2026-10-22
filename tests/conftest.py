import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["SAMPLE_MODE"] = "true"
os.environ.setdefault("EMBED_PROVIDER", "hash")  # tests never call a remote embedder unless a test opts in with a mock
