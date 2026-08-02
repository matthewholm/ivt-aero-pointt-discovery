"""Standalone check: are the exported PoinTT tokens still valid?

Run:
    python verify_token.py

Does a single GET against /gateway/versionFirmware, refreshing the access
token first if it's expired. Prints firmware info on success.
"""

from pointt_client import PointtClient, PointtAuthError, TokenState


def main() -> None:
    try:
        state = TokenState.load()
    except FileNotFoundError as err:
        print(f"ERROR: {err}")
        return

    print(f"Loaded token for gateway/device_id={state.device_id}")
    print(f"Token expires at: {state.expires_at.isoformat()}")

    try:
        client = PointtClient(state)
    except PointtAuthError as err:
        print(f"ERROR: could not obtain a valid access token: {err}")
        return

    if client.state.access_token != state.access_token:
        print("Access token was refreshed.")

    status, body = client.get("/gateway/versionFirmware")
    print(f"\nGET /gateway/versionFirmware -> HTTP {status}")
    print(body)

    if status == 200:
        print("\nTokens are valid. The gateway is reachable.")
    else:
        print("\nTokens loaded but this request failed — see status/body above.")


if __name__ == "__main__":
    main()
