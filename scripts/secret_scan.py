"""Fails (exit 1) if a likely secret is found in tracked files or in git history. Prints file and
pattern name only, never the matched value."""
import re, subprocess, sys

PATTERNS = {
    "nvidia_key": r"nvapi-[A-Za-z0-9_-]{20,}", "github_token": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "openai_like_key": r"sk-[A-Za-z0-9]{32,}", "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "slack_token": r"xox[baprs]-[A-Za-z0-9-]{10,}",
    "bearer_literal": r"Bearer [A-Za-z0-9._-]{30,}",
}
BAD_FILES = re.compile(r"(^|/)\.env$|zetaris_docker_login|\.pem$")


def main() -> int:
    hits = []
    files = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    hits += [f"{f}: forbidden file" for f in files if BAD_FILES.search(f)]
    for f in files:
        try:
            txt = open(f, encoding="utf-8", errors="ignore").read()
        except (IsADirectoryError, FileNotFoundError):
            continue
        hits += [f"{f}: {n}" for n, p in PATTERNS.items() if re.search(p, txt)]
    hist = subprocess.run(["git", "log", "--all", "-p", "--no-color"], capture_output=True, text=True, errors="ignore").stdout
    hits += [f"git history: {n}" for n, p in PATTERNS.items() if re.search(p, hist)]
    print("\n".join(hits) if hits else "secret scan: clean")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
