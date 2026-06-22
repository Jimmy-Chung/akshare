from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

RUNTIME_DIR = Path(
    os.getenv(
        "LONGBRIDGE_OAUTH_DATA_DIR",
        Path(__file__).resolve().parents[1] / "runtime_cache",
    )
)
CLIENT_FILE = RUNTIME_DIR / "longbridge_oauth_client.json"


class LongbridgeOAuthError(RuntimeError):
    pass


def oauth_base_url() -> str:
    configured = os.getenv("LONGBRIDGE_OAUTH_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    if os.getenv("LONGBRIDGE_ENV") == "staging":
        return "https://openapi.longbridge.xyz/oauth2"
    if os.getenv("LONGBRIDGE_REGION", "cn").lower() in {"hk", "global", "intl"}:
        return "https://openapi.longbridge.com/oauth2"
    return "https://openapi.longbridge.cn/oauth2"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def get_client_id() -> str:
    configured = os.getenv("LONGBRIDGE_OAUTH_CLIENT_ID", "").strip()
    if configured:
        return configured
    return str(_read_json(CLIENT_FILE).get("client_id") or "")


def token_path(client_id: Optional[str] = None) -> Optional[Path]:
    resolved_client_id = client_id or get_client_id()
    if not resolved_client_id:
        return None
    return Path.home() / ".longbridge" / "openapi" / "tokens" / resolved_client_id


def read_token(client_id: Optional[str] = None) -> Dict[str, Any]:
    path = token_path(client_id)
    return _read_json(path) if path else {}


def token_is_usable(client_id: Optional[str] = None) -> bool:
    token = read_token(client_id)
    return bool(
        token.get("access_token")
        and int(token.get("expires_at") or 0) > int(time.time()) + 300
    )


def has_refresh_token(client_id: Optional[str] = None) -> bool:
    return bool(read_token(client_id).get("refresh_token"))


def ensure_client(redirect_uri: str) -> str:
    configured_client_id = os.getenv("LONGBRIDGE_OAUTH_CLIENT_ID", "").strip()
    if configured_client_id:
        return configured_client_id

    saved_client = _read_json(CLIENT_FILE)
    client_id = str(saved_client.get("client_id") or "")
    if client_id and saved_client.get("redirect_uri") == redirect_uri:
        return client_id

    if os.getenv("LONGBRIDGE_OAUTH_AUTO_REGISTER", "true").lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise LongbridgeOAuthError(
            "未配置 LONGBRIDGE_OAUTH_CLIENT_ID，且已关闭 OAuth 客户端自动注册"
        )

    try:
        response = requests.post(
            f"{oauth_base_url()}/register",
            json={
                "client_name": os.getenv(
                    "LONGBRIDGE_OAUTH_CLIENT_NAME",
                    "Finogeeks Market Terminal",
                ),
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise LongbridgeOAuthError(f"注册 Longbridge OAuth 客户端失败：{exc}") from exc

    client_id = str(payload.get("client_id") or "")
    if not client_id:
        raise LongbridgeOAuthError("Longbridge OAuth 注册结果缺少 client_id")

    _write_json(
        CLIENT_FILE,
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "created_at": int(time.time()),
        },
    )
    return client_id


def build_authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "state": state,
            "redirect_uri": redirect_uri,
        }
    )
    return f"{oauth_base_url()}/authorize?{query}"


def _token_request(form: Dict[str, str]) -> Dict[str, Any]:
    try:
        response = requests.post(
            f"{oauth_base_url()}/token",
            data=form,
            headers={"Accept": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise LongbridgeOAuthError(f"获取 Longbridge OAuth Token 失败：{exc}") from exc

    if not payload.get("access_token"):
        raise LongbridgeOAuthError("Longbridge OAuth 响应缺少 access_token")
    return payload


def exchange_code(
    client_id: str,
    code: str,
    redirect_uri: str,
) -> Dict[str, Any]:
    payload = _token_request(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
        }
    )
    return save_token(client_id, payload)


def refresh_token(client_id: Optional[str] = None) -> Dict[str, Any]:
    resolved_client_id = client_id or get_client_id()
    current = read_token(resolved_client_id)
    refresh_value = str(current.get("refresh_token") or "")
    if not resolved_client_id or not refresh_value:
        raise LongbridgeOAuthError("没有可用于续期的 Longbridge refresh_token")

    payload = _token_request(
        {
            "grant_type": "refresh_token",
            "client_id": resolved_client_id,
            "refresh_token": refresh_value,
        }
    )
    if not payload.get("refresh_token"):
        payload["refresh_token"] = refresh_value
    return save_token(resolved_client_id, payload)


def save_token(client_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    expires_in = int(payload.get("expires_in") or 3600)
    persisted = {
        "client_id": client_id,
        "access_token": str(payload["access_token"]),
        "refresh_token": payload.get("refresh_token"),
        "expires_at": int(time.time()) + expires_in,
    }
    path = token_path(client_id)
    if path is None:
        raise LongbridgeOAuthError("无法确定 Longbridge OAuth Token 保存路径")
    _write_json(path, persisted)
    return persisted


def ensure_valid_token(client_id: Optional[str] = None) -> bool:
    resolved_client_id = client_id or get_client_id()
    if not resolved_client_id:
        return False
    if token_is_usable(resolved_client_id):
        return True
    if not has_refresh_token(resolved_client_id):
        return False
    try:
        refresh_token(resolved_client_id)
    except LongbridgeOAuthError:
        return False
    return token_is_usable(resolved_client_id)


def auth_status() -> Dict[str, Any]:
    client_id = get_client_id()
    token = read_token(client_id)
    return {
        "clientConfigured": bool(client_id),
        "authenticated": token_is_usable(client_id),
        "canRefresh": bool(token.get("refresh_token")),
        "expiresAt": token.get("expires_at"),
    }
