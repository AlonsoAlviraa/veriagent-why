"""Secret-scan patterns: synthetic secrets are built at runtime (never stored in the repo) and must be caught,
clean look-alikes must not; scan of a throwaway git repo must fail on a planted key and print no secret value."""
import random, re, string, subprocess, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import secret_scan as S

A = string.ascii_letters + string.digits


def rs(r, n, al=A):
    return "".join(r.choice(al) for _ in range(n))


def make(kind, r):
    return {"nvidia_key": lambda: "nv" + "api-" + rs(r, 40), "github_token": lambda: "gh" + r.choice("pousr") + "_" + rs(r, 36),
            "openai_like_key": lambda: "s" + "k-" + rs(r, 40), "aws_access_key": lambda: "AK" + "IA" + rs(r, 16, string.ascii_uppercase + string.digits),
            "private_key": lambda: "-----BEGIN " + r.choice(["RSA ", "EC ", ""]) + "PRIVATE" + " KEY-----",
            "slack_token": lambda: "xo" + "x" + r.choice("baprs") + "-" + rs(r, 24), "bearer_literal": lambda: "Bea" + "rer " + rs(r, 40)}[kind]()


@pytest.mark.parametrize("kind", sorted(S.PATTERNS))
@pytest.mark.parametrize("seed", range(25))
def test_pattern_catches_synthetic_secret(kind, seed):
    r = random.Random(seed); sec = make(kind, r)
    txt = f"config = '{sec}'\n"
    assert re.search(S.PATTERNS[kind], txt)


CLEAN = ["nvapi-short", "sk-123", "AKIA123", "Bearer token", "ghp_abc", "BEGIN PUBLIC KEY", "xoxb-", "NVIDIA_API_KEY=${NVIDIA_API_KEY}",
         "os.environ['NEBIUS_API_KEY']", "Authorization: Bearer {key}", "sha256:" + "a" * 64]


@pytest.mark.parametrize("txt", CLEAN)
def test_clean_lookalikes_not_flagged(txt):
    assert not any(re.search(p, txt) for p in S.PATTERNS.values())


@pytest.mark.parametrize("fname,bad", [(".env", True), ("sub/.env", True), ("zetaris_docker_login.txt", True), ("k.pem", True),
                                       (".env.example", False), ("env.py", False), ("docs/pem.md", False)])
def test_forbidden_files(fname, bad):
    assert bool(S.BAD_FILES.search(fname)) == bad


@pytest.mark.parametrize("kind", sorted(S.PATTERNS))
def test_scan_fails_on_planted_secret_without_printing_it(tmp_path, kind):
    sec = make(kind, random.Random(7))
    g = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True, check=True)
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    (tmp_path / "a.txt").write_text("hello\n"); g("add", "."); g("commit", "-qm", "a")
    out = subprocess.run([sys.executable, str(ROOT / "scripts/secret_scan.py")], cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0
    (tmp_path / "b.txt").write_text(sec); g("add", "."); g("commit", "-qm", "b")
    (tmp_path / "b.txt").write_text("removed\n"); g("commit", "-qam", "c")  # still in history
    out = subprocess.run([sys.executable, str(ROOT / "scripts/secret_scan.py")], cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 1 and kind in out.stdout and sec not in out.stdout + out.stderr
