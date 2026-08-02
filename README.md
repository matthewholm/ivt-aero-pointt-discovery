# ivt-aero-pointt-discovery

Standalone Python tools for verifying OAuth2 tokens and mapping the resource
schema of Bosch's PoinTT cloud API (`pointt-api.bosch-thermotechnology.com`),
used by the Bosch/IVT/Buderus **K30/K40 wifi gateway** family (IVT Aero,
Bosch Climate 3000i/5000i/8000i, Buderus, Junkers, Worcester equivalents).

Written while debugging a Home Assistant setup for an **IVT Aero** air-to-air
heat pump connected via a **K30** gateway.

Requires Python 3.10+ (uses `X | None` union-type syntax).

## Quick start

```bash
pip install truststore
mkdir secrets   # then create secrets/ivt_token_entry.json, see below

python scripts/verify_token.py       # confirms your tokens work
python scripts/crawl_tree.py         # maps the resource tree for your device
python scripts/discover_endpoints.py # sweeps a fixed list of known paths
```

## Key finding

The PoinTT API resource tree is **not the same** for every device family:

- **Hydronic systems** (boilers, ground/water source heat pumps) expose
  `/heatingCircuits/hc1/...`, `/dhwCircuits/dhw1/...`, `/heatSources/...`.
- **RAC devices** (Residential Air Conditioning — ductless split/air-to-air
  units, which is what "IVT Aero" actually is, running ECHONET Lite
  internally) expose a completely different tree under
  `/airConditioning/...`. The hydronic paths all 404 on these devices, and
  vice versa.

You can tell which family a gateway belongs to from the account's device
list (see [`scripts/pointt_client.py`](scripts/pointt_client.py) and
[`results/endpoint_discovery.json`](results/endpoint_discovery.json)):

```
GET https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/gateways
-> [{"deviceId": "...", "deviceType": "rac"}]   # RAC = airConditioning schema
```

`deviceType` values seen in the wild (via the
[`homecom_alt`](https://pypi.org/project/homecom-alt/) library, which this
project cross-referenced): `rac`, `k30`/`k40` (boiler), `wddw2` (water
heater), `icom` (heat pump), `rrc2` (thermostat), `commodule` (EV charger).

## The device_id pitfall

Several community Home Assistant integrations for this API ask the user to
manually type in a "device ID / serial number" during setup. **The physical
serial number printed on the unit's sticker is not the same thing as the
`deviceId` the API expects** — that's a separate, short numeric gateway ID
that only shows up in the account's `/gateways` listing (see above). Using
the sticker serial number as `deviceId` produces:

```json
{"code": 400, "httpStatus": "BAD_REQUEST",
 "message": "invalid or missing parameter [deviceId]: <sticker serial>"}
```

If you're hitting this, fetch `/gateways` with a valid token (see
`scripts/verify_token.py` for a working auth flow) and use the `deviceId`
from there instead.

## Recommended Home Assistant integration

For RAC devices (IVT Aero, Bosch Climate 5000i, etc.), use
[serbanb11/bosch-homecom-hass](https://github.com/serbanb11/bosch-homecom-hass) —
an actively maintained integration built on the published
[`homecom_alt`](https://pypi.org/project/homecom-alt/) library, which already
implements the `/airConditioning/*` schema documented here. This repo's
scripts were used to independently verify that schema against a real device
before adopting that integration.

## Scripts

All scripts are standalone (no Home Assistant runtime needed) and only
depend on the Python standard library plus
[`truststore`](https://pypi.org/project/truststore/) (lets Python use the
OS certificate store — useful if a local proxy/AV does TLS inspection).

```
pip install truststore
```

- **`pointt_client.py`** — minimal OAuth2 + REST client. Loads tokens from
  `secrets/ivt_token_entry.json` (gitignored, never commit this file —
  see below for how to obtain it), auto-refreshes expired access tokens.
- **`verify_token.py`** — sanity check: one GET against
  `/gateway/versionFirmware` to confirm the tokens are valid.
- **`discover_endpoints.py`** — sweeps a fixed list of candidate resource
  paths with GET, records 200 vs 400/403/404 for each, writes
  `results/endpoint_discovery_<timestamp>.json`.
- **`crawl_tree.py`** — recursively follows the API's self-describing
  `refEnum`/`bulk` category nodes (e.g. `GET /system` returns a list of its
  real children) instead of guessing paths, writes
  `results/resource_tree_<timestamp>.json`. This is the more reliable of
  the two discovery methods, since 403 is used generically for both
  "exists but forbidden" and "made-up top-level path" — it can't be used to
  brute-force unknown top-level categories, but works well once you know a
  category's real entry point.

### Getting a token file

These scripts expect `secrets/ivt_token_entry.json` (create the `secrets/`
directory yourself — it's gitignored):

```json
{
  "device_id": "<numeric gateway ID from /gateways, NOT the sticker serial>",
  "access_token": "...",
  "refresh_token": "...",
  "token_expires_at": "2026-01-01T00:00:00+00:00"
}
```

If you already have a working OAuth2-based integration (Home Assistant or
otherwise) for this API, its stored config entry / token cache will have
these same four fields under different key names.

## Results

[`results/endpoint_discovery.json`](results/endpoint_discovery.json) and
[`results/resource_tree.json`](results/resource_tree.json) are the actual
output from running these scripts against a real IVT Aero + K30 gateway.
Account-identifying fields (`device_id`, `serialId`, MAC address, wifi SSID)
are redacted; everything else (paths, types, allowed values, units) is
exactly as returned by the API.

## Disclaimer

This uses an unofficial, observed API. Bosch can change endpoints, scopes,
or payloads at any time without notice.
