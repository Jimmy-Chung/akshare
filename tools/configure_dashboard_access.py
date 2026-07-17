#!/usr/bin/env python3
from __future__ import annotations

import getpass
import os
import secrets
import tempfile
from pathlib import Path

from werkzeug.security import generate_password_hash


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def _updated_env(existing: str, values: dict[str, str]) -> str:
    remaining = dict(values)
    lines = []
    for raw_line in existing.splitlines():
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#") and "=" in raw_line:
            key = raw_line.split("=", 1)[0].strip()
            if key in remaining:
                lines.append(f"{key}={remaining.pop(key)}")
                continue
        lines.append(raw_line)
    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Financial dashboard 网页访问凭证")
        lines.extend(f"{key}={value}" for key, value in remaining.items())
    return "\n".join(lines).rstrip() + "\n"


def configure(env_path: Path = ENV_PATH) -> None:
    password = getpass.getpass("网页访问凭证（至少 12 个字符，输入不会显示）: ")
    if len(password) < 12:
        raise SystemExit("访问凭证至少需要 12 个字符，配置未修改。")
    confirmation = getpass.getpass("再次输入访问凭证: ")
    if not confirmation or not secrets_match(password, confirmation):
        raise SystemExit("两次输入不一致，配置未修改。")

    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    content = _updated_env(existing, {
        "DASHBOARD_ACCESS_PASSWORD_HASH": generate_password_hash(password),
        "DASHBOARD_ACCESS_SESSION_DAYS": "30",
    })
    env_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".env.", dir=env_path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, env_path)
    finally:
        temporary.unlink(missing_ok=True)
    print("网页访问凭证已以密码哈希写入本机 .env；明文未保存。")


def secrets_match(left: str, right: str) -> bool:
    return secrets.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


if __name__ == "__main__":
    configure()
