"""Get a fresh secrets/ivt_token_entry.json from scratch, with no existing
Home Assistant integration required — just a browser login.

The authorization code this needs is short-lived (observed: well under a
minute), and single-use. Do the whole browser step immediately before
running this script, not in advance.

Usage:
    python scripts/get_tokens.py "<code>"

If you omit the code, the script prints the login URL and waits for you to
paste the code back in.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import truststore

truststore.inject_into_ssl()

from pointt_client import CLIENT_ID, TOKEN_URL, TokenState, _http_json  # noqa: E402

SECRETS_PATH = Path(__file__).resolve().parent.parent / "secrets" / "ivt_token_entry.json"

REDIRECT_URI = "com.bosch.tt.dashtt.pointt://app/login"

# Fixed PKCE code_verifier matching the code_challenge baked into LOGIN_URL
# below (same pair used by github.com/serbanb11/bosch-homecom-hass's browser
# auth flow, cross-referenced from the published `homecom_alt` library).
CODE_VERIFIER = "AZbpLzMvXigq_jz7_riwNDV8BQYT30prXGDyRHdQMo0GYre3si9YJfG4b1U-QWERtOiX_9mCJE2SAPvJMeM2yA"

LOGIN_URL = (
    "https://singlekey-id.com/auth/en-us/login?state=nKqS17oMAxqUsQpMznajIr"
    "&nonce=5yPvyTqMS3iPb4c8RfGJg1"
    "&code_challenge=Fc6eY3uMBJkFqa4VqcULuLuKC5Do70XMw7oa_Pxafw0"
    f"&redirect_uri={REDIRECT_URI}"
    f"&client_id={CLIENT_ID}"
    "&response_type=code&prompt=login"
    "&scope=openid+email+profile+offline_access"
    "+pointt.gateway.claiming+pointt.gateway.removal+pointt.gateway.list"
    "+pointt.gateway.users+pointt.gateway.resource.dashapp"
    "+pointt.castt.flow.token-exchange+bacon"
    "&code_challenge_method=S256&style_id=tt_bsch"
)

GATEWAYS_URL = "https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/gateways"


def get_code_from_user() -> str:
    print("1. Open this URL in a browser and log in with your Bosch/IVT account:\n")
    print(f"   {LOGIN_URL}\n")
    print("2. After login, the browser will try to redirect to a custom app URL")
    print(f"   ('{REDIRECT_URI}?code=...') and fail to open it — that's expected,")
    print("   it's meant for the mobile app, not a browser.")
    print("3. Grab the failed URL from your browser's address bar, or from")
    print("   DevTools (F12) -> Console/Network with 'Preserve log' on.")
    print("4. Copy just the value between 'code=' and the next '&'.\n")
    print("Do steps 1-4 now, then paste the code below immediately — it expires fast.\n")
    return input("code: ").strip()


def exchange_code(code: str) -> dict:
    status, body = _http_json(
        TOKEN_URL,
        method="POST",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "code_verifier": CODE_VERIFIER,
        },
        form=True,
    )
    if status != 200 or "access_token" not in body:
        raise SystemExit(
            f"Token exchange failed (HTTP {status}): {body}\n"
            "Most likely cause: the code already expired or was already used. "
            "Get a fresh one and run this again immediately."
        )
    return body


def list_gateways(access_token: str) -> list[dict]:
    status, body = _http_json(GATEWAYS_URL, headers={"Authorization": f"Bearer {access_token}"})
    if status != 200:
        raise SystemExit(f"Could not list gateways (HTTP {status}): {body}")
    return body


def main() -> None:
    code = sys.argv[1].strip() if len(sys.argv) > 1 else get_code_from_user()

    tokens = exchange_code(code)
    print("\nToken exchange OK.")

    gateways = list_gateways(tokens["access_token"])
    if not gateways:
        raise SystemExit("Account has no gateways registered — nothing to save.")

    if len(gateways) > 1:
        print("\nMultiple gateways found on this account:")
        for i, gw in enumerate(gateways):
            print(f"  [{i}] deviceId={gw['deviceId']} deviceType={gw['deviceType']}")
        idx = int(input("Which one? [0]: ").strip() or "0")
    else:
        idx = 0
    device_id = gateways[idx]["deviceId"]
    print(f"Using gateway deviceId={device_id} (deviceType={gateways[idx]['deviceType']})")

    expires_in = tokens.get("expires_in", 3600)
    state = TokenState(
        device_id=device_id,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    )
    SECRETS_PATH.parent.mkdir(exist_ok=True)
    state.save(SECRETS_PATH)
    print(f"\nSaved {SECRETS_PATH}. Run scripts/verify_token.py to confirm it works.")


if __name__ == "__main__":
    main()
