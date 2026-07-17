#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import os
import tempfile
from pathlib import Path


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
        lines.append("# AI 市场助手（本机配置）")
        lines.extend(f"{key}={value}" for key, value in remaining.items())
    return "\n".join(lines).rstrip() + "\n"


def configure(env_path: Path = ENV_PATH) -> None:
    api_key = getpass.getpass("DeepSeek API Key（输入不会显示）: ").strip()
    if not api_key:
        raise SystemExit("未输入 API Key，配置未修改。")
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    content = _updated_env(existing, {
        "AI_ASSISTANT_PROVIDER": "deepseek",
        "DEEPSEEK_API_KEY": api_key,
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
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
    print("DeepSeek 已写入本机 .env；API Key 未显示。")


def main() -> None:
    parser = argparse.ArgumentParser(description="Securely configure the local DeepSeek API key.")
    parser.parse_args()
    configure()


if __name__ == "__main__":
    main()
