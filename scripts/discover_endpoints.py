"""Sweep candidate PoinTT resource paths with GET and record what this
specific gateway (IVT Aero / K30) actually supports.

Two path sets are tested:
  - KNOWN_PATHS: every leaf path the fuatsengul/ivt-heatpump-ha integration
    already polls (from its const.py) — these are known-good on *some*
    K30-connected devices, but not necessarily this one.
  - PROBE_PATHS: parent/category paths and a few extra leaves that are
    common in the Bosch PoinTT resource tree, to see if this device exposes
    more (or less) than the integration currently assumes.

Run:
    python discover_endpoints.py

Writes results/endpoint_discovery_<timestamp>.json with one entry per path:
    {"path": ..., "status": 200, "ok": true, "body": {...}}
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from pointt_client import PointtClient, PointtAuthError, TokenState

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

# Every path the current integration polls (source: upstream-src/const.py)
KNOWN_PATHS = [
    # Heating circuit
    "/heatingCircuits/hc1/roomtemperature",
    "/heatingCircuits/hc1/currentRoomSetpoint",
    "/heatingCircuits/hc1/temporaryRoomSetpoint",
    "/heatingCircuits/hc1/operationMode",
    "/heatingCircuits/hc1/activeSwitchProgram",
    "/heatingCircuits/hc1/overallStatus",
    "/heatingCircuits/hc1/temperatureLevels/comfort2",
    "/heatingCircuits/hc1/temperatureLevels/eco",
    "/heatingCircuits/hc1/maxFlowTemp",
    "/heatingCircuits/hc1/heatingType",
    "/heatingCircuits/hc1/controlType",
    "/heatingCircuits/hc1/heatCoolMode",
    "/heatingCircuits/hc1/currentSuWiMode",
    "/heatingCircuits/hc1/suWiSwitchMode",
    "/heatingCircuits/hc1/suWiThreshold",
    # DHW
    "/dhwCircuits/dhw1/actualTemp",
    "/dhwCircuits/dhw1/currentSetpoint",
    "/dhwCircuits/dhw1/operationMode",
    "/dhwCircuits/dhw1/overallStatus",
    "/dhwCircuits/dhw1/charge",
    "/dhwCircuits/dhw1/chargeDuration",
    "/dhwCircuits/dhw1/singleChargeSetpoint",
    "/dhwCircuits/dhw1/reduceTempOnAlarm",
    "/dhwCircuits/dhw1/tdMode",
    "/dhwCircuits/dhw1/temperatureLevels/eco",
    "/dhwCircuits/dhw1/temperatureLevels/high",
    "/dhwCircuits/dhw1/temperatureLevels/low",
    "/dhwCircuits/dhw1/temperatureLevels/off",
    # Heat sources
    "/heatSources/actualModulation",
    "/heatSources/actualSupplyTemperature",
    "/heatSources/returnTemperature",
    "/heatSources/chStatus",
    "/heatSources/actualHeatDemand",
    "/heatSources/numberOfStarts",
    "/heatSources/hs1/type",
    "/heatSources/hs1/heatPumpType",
    "/heatSources/standbyMode",
    "/heatSources/emStatus",
    "/heatSources/hs1/numberOfStarts",
    # System
    "/system/sensors/temperatures/outdoor_t1",
    "/system/dateTime",
    "/system/bus",
    "/system/brand",
    "/system/country",
    "/system/type",
    "/system/info",
    # Gateway
    "/gateway/versionFirmware",
    "/gateway/versionHardware",
    "/gateway/dateTime",
    "/gateway/uuid",
    "/gateway/wifi/ip/ipv4",
    "/gateway/wifi/mac",
    "/gateway/wifi/ssid",
    "/gateway/serialId",
    "/gateway/swPrefix",
    "/gateway/tzInfo/timeZone",
    # Notifications
    "/notifications",
    # Recordings (energy monitoring)
    "/recordings/heatSources/emon/total/compressor",
    "/recordings/heatSources/emon/total/eheater",
    "/recordings/heatSources/emon/total/outputProduced",
    "/recordings/heatSources/emon/ch/compressor",
    "/recordings/heatSources/emon/ch/eheater",
    "/recordings/heatSources/emon/ch/outputProduced",
    "/recordings/heatSources/emon/dhw/compressor",
    "/recordings/heatSources/emon/dhw/eheater",
    "/recordings/heatSources/emon/dhw/outputProduced",
    # Variable tariff (known to 400 on this device, testing anyway to confirm)
    "/system/variableTariff/ch/optimization",
    "/system/variableTariff/ch/highPriceDelta",
    "/system/variableTariff/ch/lowPriceDelta",
    "/system/variableTariff/ch/midPriceSetpoint",
    "/system/variableTariff/dhw/optimization",
    "/system/variableTariff/dhw/highPriceEnable",
    "/system/variableTariff/dhw/lowPriceEnable",
]

# Category/parent paths + extra leaves not currently polled by the
# integration, common elsewhere in the Bosch PoinTT resource tree.
PROBE_PATHS = [
    "/heatingCircuits",
    "/heatingCircuits/hc1",
    "/dhwCircuits",
    "/dhwCircuits/dhw1",
    "/heatSources",
    "/heatSources/hs1",
    "/system",
    "/system/sensors",
    "/system/sensors/temperatures",
    "/system/variableTariff",
    "/system/variableTariff/ch",
    "/system/variableTariff/dhw",
    "/gateway",
    "/recordings",
    "/recordings/heatSources",
    "/recordings/heatSources/emon",
]

ALL_PATHS = [(p, "known") for p in KNOWN_PATHS] + [(p, "probe") for p in PROBE_PATHS]


def main() -> None:
    try:
        state = TokenState.load()
    except FileNotFoundError as err:
        print(f"ERROR: {err}")
        return

    try:
        client = PointtClient(state)
    except PointtAuthError as err:
        print(f"ERROR: could not obtain a valid access token: {err}")
        return

    results = []
    print(f"Testing {len(ALL_PATHS)} paths against gateway {client.state.device_id}...\n")

    for path, source in ALL_PATHS:
        status, body = client.get(path)
        ok = status == 200
        marker = "OK " if ok else "ERR"
        print(f"[{marker}] {status:>3}  {path}")
        results.append(
            {
                "path": path,
                "source": source,
                "status": status,
                "ok": ok,
                "body": body,
            }
        )
        time.sleep(0.3)  # be gentle with the K30 — it doesn't like bursts

    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"endpoint_discovery_{timestamp}.json"
    out_path.write_text(
        json.dumps(
            {
                "device_id": client.state.device_id,
                "tested_at": datetime.now(timezone.utc).isoformat(),
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    working = [r for r in results if r["ok"]]
    failing = [r for r in results if not r["ok"]]
    print(f"\n{len(working)} working, {len(failing)} failing. Full results: {out_path}")


if __name__ == "__main__":
    main()
