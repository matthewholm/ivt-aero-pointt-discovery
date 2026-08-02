"""Minimal standalone client for the Bosch PoinTT API (IVT Aero / K30 gateway).

Loads OAuth2 tokens from a local, gitignored secrets file (never commit this
file or paste its contents anywhere) and talks directly to the PoinTT REST
API used by the Bosch/IVT mobile app and the ivt-heatpump-ha integration.

Token source: exported from Home Assistant's `.storage/core.config_entries`
(config entry for the `ivt_heatpump` custom component), which stores
access_token / refresh_token / token_expires_at directly on the entry.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import truststore

# Use the OS-native certificate store (Windows Certificate Store) instead of
# Python's bundled CA list. Needed when a local proxy/AV does TLS inspection
# with a root CA that's trusted by Windows but not by Python's own bundle.
truststore.inject_into_ssl()

SECRETS_PATH = Path(__file__).resolve().parent.parent / "secrets" / "ivt_token_entry.json"

TOKEN_URL = "https://singlekey-id.com/auth/connect/token"
CLIENT_ID = "762162C0-FA2D-4540-AE66-6489F189FADC"
POINTT_BASE_URL = "https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/gateways/"


class PointtAuthError(Exception):
    """Raised when authentication/token refresh fails."""


@dataclass
class TokenState:
    device_id: str
    access_token: str
    refresh_token: str
    expires_at: datetime

    @classmethod
    def load(cls, path: Path = SECRETS_PATH) -> "TokenState":
        if not path.exists():
            raise FileNotFoundError(
                f"Token file not found at {path}. Export it from Home Assistant's "
                "core.config_entries first (see README)."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            device_id=data["device_id"],
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.fromisoformat(data["token_expires_at"]),
        )

    def save(self, path: Path = SECRETS_PATH) -> None:
        path.write_text(
            json.dumps(
                {
                    "device_id": self.device_id,
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                    "token_expires_at": self.expires_at.isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def is_expired(self, skew_minutes: int = 5) -> bool:
        return datetime.now(timezone.utc) >= (self.expires_at - timedelta(minutes=skew_minutes))


def _http_json(
    url: str,
    method: str = "GET",
    data: dict | bytes | None = None,
    headers: dict | None = None,
    form: bool = False,
    timeout: int = 30,
) -> tuple[int, dict | str]:
    """Tiny stdlib HTTP helper. Returns (status_code, parsed_json_or_text)."""
    body = None
    req_headers = dict(headers or {})
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            req_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            body = json.dumps(data).encode()
            req_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        status = err.code
    except urllib.error.URLError as err:
        raise PointtAuthError(f"Connection error calling {url}: {err}") from err

    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = raw
    return status, parsed


def refresh_access_token(state: TokenState) -> TokenState:
    """Exchange the refresh token for a new access token."""
    status, payload = _http_json(
        TOKEN_URL,
        method="POST",
        data={
            "grant_type": "refresh_token",
            "refresh_token": state.refresh_token,
            "client_id": CLIENT_ID,
        },
        form=True,
    )
    if status != 200 or not isinstance(payload, dict) or "access_token" not in payload:
        raise PointtAuthError(f"Token refresh failed (HTTP {status}): {payload}")

    expires_in = payload.get("expires_in", 3600)
    new_state = TokenState(
        device_id=state.device_id,
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token", state.refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    )
    return new_state


def ensure_fresh_token(state: TokenState) -> TokenState:
    """Refresh + persist the token if it's expired or close to expiring."""
    if state.is_expired():
        state = refresh_access_token(state)
        state.save()
    return state


class PointtClient:
    """Direct GET/PUT client for one gateway's `/resource` tree."""

    def __init__(self, state: TokenState):
        self.state = ensure_fresh_token(state)
        self.base_url = f"{POINTT_BASE_URL}{self.state.device_id}/resource"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.state.access_token}"}

    def get(self, path: str, retry_on_auth_error: bool = True) -> tuple[int, dict | str]:
        """GET a resource path. Returns (status_code, body)."""
        url = f"{self.base_url}{path}"
        status, body = _http_json(url, headers=self._headers())
        if status == 401 and retry_on_auth_error:
            self.state = refresh_access_token(self.state)
            self.state.save()
            return self.get(path, retry_on_auth_error=False)
        return status, body

    def put(self, path: str, value, retry_on_auth_error: bool = True) -> tuple[int, dict | str]:
        """PUT {"value": value} to a resource path. Returns (status_code, body)."""
        url = f"{self.base_url}{path}"
        status, body = _http_json(
            url, method="PUT", data={"value": value}, headers=self._headers()
        )
        if status == 401 and retry_on_auth_error:
            self.state = refresh_access_token(self.state)
            self.state.save()
            return self.put(path, value, retry_on_auth_error=False)
        return status, body
