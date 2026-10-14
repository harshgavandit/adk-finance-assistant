"""Check the Git index for forbidden runtime files and common secret patterns.

Only filenames and finding categories are printed; never matched secret values.
This is a pre-publication aid, not a comprehensive secret scanner. Compressed
PDF contents require a separate document-content review.
"""
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "OpenAI credential": rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}",
    "Google credential": rb"AIza[A-Za-z0-9_-]{30,}",
    "GitHub credential": rb"gh[opusr]_[A-Za-z0-9]{20,}",
    "GitHub fine-grained credential": rb"github_pat_[A-Za-z0-9_]{30,}",
    "private key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def configured_secrets() -> list[bytes]:
    # Inspect local dotenv files in-memory only, without printing values.
    secrets = []
    for env_path in (ROOT / ".env", ROOT / "ADK_Finance_Assistance_Agent" / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.partition("=")
            if separator and any(word in name.upper() for word in ("KEY", "TOKEN", "PASSWORD", "SECRET")):
                value = value.strip().strip('"').strip("'")
                if len(value) >= 10:
                    secrets.append(value.encode())
    return secrets


def main() -> int:
    names = [item.decode("utf-8") for item in git("ls-files", "-z").split(b"\0") if item]
    if not names:
        print("FAIL: no tracked files to inspect. Stage the publishable files first.")
        return 1
    secrets = configured_secrets()
    findings = []
    forbidden_parts = {".venv", ".tmp", ".runtime", ".adk", "__MACOSX", "__pycache__", ".pytest_cache"}
    for name in names:
        path = PurePosixPath(name)
        if (path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example")
                or forbidden_parts.intersection(path.parts)
                or path.suffix in {".db", ".sqlite3", ".pyc", ".log"}
                or path.name == ".DS_Store"):
            findings.append((name, "runtime or private file"))
        payload = git("show", f":{name}")
        for label, pattern in PATTERNS.items():
            if re.search(pattern, payload):
                findings.append((name, label))
        if any(secret in payload for secret in secrets):
            findings.append((name, "configured local secret"))
    for name, label in findings:
        print(f"FAIL: {name}: {label}")
    print(f"Checked {len(names)} tracked files; findings: {len(findings)}.")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
