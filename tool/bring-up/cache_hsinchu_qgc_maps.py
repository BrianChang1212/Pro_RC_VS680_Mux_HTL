#!/usr/bin/env python3
"""Cache a small Hsinchu downtown tile set into board QGC map DB, then exit.

Targets default QGC map (Bing Hybrid). APK on VS680 includes Google providers,
so Bing Hybrid mapId = 8 (see UrlFactory::_providers order).

Usage:
  python cache_hsinchu_qgc_maps.py
  python cache_hsinchu_qgc_maps.py --serial 83bc469a34914114 --zoom 16
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

QGC_PKG = "org.mavlink.qgroundcontrolbeta"
QGC_ACTIVITY = "org.mavlink.qgroundcontrol.QGCActivity"
MAP_DB_REL = f"/data/user/0/{QGC_PKG}/files/QGCMapCache300/qgcMapCache.db"
INI_REL = f"/data/user/0/{QGC_PKG}/files/.config/QGroundControl.org/QGroundControl.ini"

# Hsinchu downtown (station / city core), small bbox ~2 km
HSINCHU_LAT = 24.8039
HSINCHU_LON = 120.9715
# N, W, S, E
BBOX = (24.8150, 120.9580, 24.7920, 120.9850)

# Google providers compiled in (confirmed in board APK strings)
BING_HYBRID_MAP_ID = 8
MAP_TYPE_STR = "Bing Hybrid"
TILE_FORMAT = "jpg"
BING_TYPE_CODE = "h"
BING_VERSION = "2981"

SET_NAME = "Hsinchu City"


def adb(serial: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["adb", "-s", serial, *args]
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def adb_shell(serial: str, shell_cmd: str, check: bool = True) -> str:
    r = adb(serial, "shell", shell_cmd, check=check)
    return (r.stdout or "").strip()


def long2tile_x(lon: float, z: int) -> int:
    return int(math.floor((lon + 180.0) / 360.0 * (2.0**z)))


def lat2tile_y(lat: float, z: int) -> int:
    lat_r = math.radians(lat)
    return int(
        math.floor(
            (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi)
            / 2.0
            * (2.0**z)
        )
    )


def tile_xy_to_quadkey(tile_x: int, tile_y: int, zoom: int) -> str:
    digits = []
    for i in range(zoom, 0, -1):
        digit = 0
        mask = 1 << (i - 1)
        if tile_x & mask:
            digit += 1
        if tile_y & mask:
            digit += 2
        digits.append(str(digit))
    return "".join(digits)


def tile_hash(map_id: int, x: int, y: int, z: int) -> str:
    return f"{map_id:010d}{x:08d}{y:08d}{z:03d}"


def bing_url(x: int, y: int, z: int) -> str:
    server = (x + 2 * y) % 4
    qk = tile_xy_to_quadkey(x, y, z)
    return (
        f"http://ecn.t{server}.tiles.virtualearth.net/tiles/"
        f"{BING_TYPE_CODE}{qk}.{TILE_FORMAT}?g={BING_VERSION}&mkt=en"
    )


def download_tile(x: int, y: int, z: int, retries: int = 3) -> bytes:
    url = bing_url(x, y, z)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; AcctonQGCMapCache/1.0)",
            "Referer": "https://www.bing.com/maps/",
        },
    )
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            if len(data) < 100:
                raise RuntimeError(f"tile too small ({len(data)} bytes)")
            # JPEG magic or PNG
            if not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError("unexpected tile image magic")
            return data
        except (urllib.error.URLError, RuntimeError, TimeoutError) as exc:
            last_err = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"download failed {url}: {last_err}")


def resolve_serial(explicit: str) -> str:
    if explicit:
        return explicit
    out = subprocess.run(["adb", "devices"], check=True, capture_output=True, text=True)
    serials = []
    for line in out.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    if len(serials) == 1:
        return serials[0]
    if not serials:
        raise SystemExit("No adb device")
    raise SystemExit(f"Multiple devices: {serials}. Pass --serial.")


def get_app_uid(serial: str) -> str:
    # e.g. u0_a79
    raw = adb_shell(serial, f"su 0 stat -c %U {MAP_DB_REL}")
    if raw.startswith("u"):
        return raw
    # fallback from dumpsys
    dump = adb_shell(serial, f"dumpsys package {QGC_PKG} | grep userId=", check=False)
    for tok in dump.replace("=", " ").split():
        if tok.isdigit():
            return f"u0_a{int(tok) - 10000}" if int(tok) >= 10000 else f"u0_a{tok}"
    return "u0_a79"


def pull_file(serial: str, remote: str, local: Path) -> None:
    tmp = f"/sdcard/Download/{local.name}"
    adb_shell(serial, f"su 0 cp {remote} {tmp}")
    adb_shell(serial, f"su 0 chmod 644 {tmp}")
    adb(serial, "pull", tmp, str(local))
    adb_shell(serial, f"rm -f {tmp}", check=False)


def push_file(serial: str, local: Path, remote: str, owner: str) -> None:
    tmp = f"/sdcard/Download/{local.name}"
    adb(serial, "push", str(local), tmp)
    adb_shell(serial, f"su 0 cp {tmp} {remote}")
    adb_shell(serial, f"su 0 chown {owner}:{owner} {remote}")
    adb_shell(serial, f"su 0 chmod 600 {remote}")
    adb_shell(serial, f"rm -f {tmp}", check=False)


def patch_ini(text: str, lat: float, lon: float, zoom: float) -> str:
    lines = text.splitlines()
    out: list[str] = []
    section = ""
    have_flight_map = False
    have_flight_pos = False
    keys_pos = {"Latitude": f"{lat}", "Longitude": f"{lon}", "FlightMapZoom": f"{zoom}"}
    # Defaults in FlightMap.SettingsGroup.json: provider=Bing, type=Hybrid
    # Fly view resolves to "Bing Hybrid" for UrlFactory tile hashes.
    keys_map = {"mapProvider": "Bing", "mapType": "Hybrid"}
    seen_pos: set[str] = set()
    seen_map: set[str] = set()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            # flush missing keys before leaving section
            if section == "FlightMapPosition":
                for k, v in keys_pos.items():
                    if k not in seen_pos:
                        out.append(f"{k}={v}")
            if section == "FlightMap":
                for k, v in keys_map.items():
                    if k not in seen_map:
                        out.append(f"{k}={v}")
            section = stripped[1:-1]
            if section == "FlightMapPosition":
                have_flight_pos = True
                seen_pos.clear()
            if section == "FlightMap":
                have_flight_map = True
                seen_map.clear()
            out.append(line)
            i += 1
            continue

        if section == "FlightMapPosition" and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in keys_pos:
                out.append(f"{key}={keys_pos[key]}")
                seen_pos.add(key)
                i += 1
                continue
        if section == "FlightMap" and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in keys_map:
                out.append(f"{key}={keys_map[key]}")
                seen_map.add(key)
                i += 1
                continue
        out.append(line)
        i += 1

    if section == "FlightMapPosition":
        for k, v in keys_pos.items():
            if k not in seen_pos:
                out.append(f"{k}={v}")
    if section == "FlightMap":
        for k, v in keys_map.items():
            if k not in seen_map:
                out.append(f"{k}={v}")

    if not have_flight_pos:
        out.extend(
            [
                "",
                "[FlightMapPosition]",
                f"FlightMapZoom={zoom}",
                f"Latitude={lat}",
                f"Longitude={lon}",
            ]
        )
    if not have_flight_map:
        out.extend(
            [
                "",
                "[FlightMap]",
                "mapProvider=Bing",
                "mapType=Hybrid",
            ]
        )
    return "\n".join(out) + "\n"


def insert_tiles(db_path: Path, zoom: int, map_id: int) -> int:
    north, west, south, east = BBOX
    x0 = long2tile_x(west, zoom)
    x1 = long2tile_x(east, zoom)
    y0 = lat2tile_y(north, zoom)
    y1 = lat2tile_y(south, zoom)
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0

    coords = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    print(
        f"Hsinchu bbox tiles z={zoom}: x={x0}..{x1} y={y0}..{y1} "
        f"count={len(coords)} mapId={map_id} ({MAP_TYPE_STR})"
    )
    if len(coords) > 80:
        raise SystemExit(f"Tile count {len(coords)} too large; tighten bbox/zoom")

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        now = int(time.time())
        cur.execute("DELETE FROM SetTiles WHERE setID IN (SELECT setID FROM TileSets WHERE name=?)", (SET_NAME,))
        cur.execute("DELETE FROM TileSets WHERE name=?", (SET_NAME,))
        cur.execute(
            "INSERT INTO TileSets(name, typeStr, topleftLat, topleftLon, bottomRightLat, "
            "bottomRightLon, minZoom, maxZoom, type, numTiles, defaultSet, date) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,0,?)",
            (
                SET_NAME,
                MAP_TYPE_STR,
                north,
                west,
                south,
                east,
                zoom,
                zoom,
                map_id,
                len(coords),
                now,
            ),
        )
        set_id = cur.lastrowid

        # Also attach to Default Tile Set (setID=1) so Fly view cache hits
        cur.execute("SELECT setID FROM TileSets WHERE defaultSet=1 LIMIT 1")
        row = cur.fetchone()
        default_set = row[0] if row else 1

        ok = 0
        for idx, (x, y) in enumerate(coords, 1):
            img = download_tile(x, y, zoom)
            h = tile_hash(map_id, x, y, zoom)
            cur.execute(
                "INSERT OR IGNORE INTO Tiles(hash, format, tile, size, type, date) "
                "VALUES(?,?,?,?,?,?)",
                (h, TILE_FORMAT, img, len(img), map_id, now),
            )
            cur.execute("SELECT tileID FROM Tiles WHERE hash=?", (h,))
            tile_id = cur.fetchone()[0]
            cur.execute(
                "INSERT OR IGNORE INTO SetTiles(tileID, setID) VALUES(?,?)",
                (tile_id, set_id),
            )
            cur.execute(
                "INSERT OR IGNORE INTO SetTiles(tileID, setID) VALUES(?,?)",
                (tile_id, default_set),
            )
            ok += 1
            if idx == 1 or idx == len(coords) or idx % 5 == 0:
                print(f"  cached {idx}/{len(coords)} ({len(img)} bytes)")
        conn.commit()
        print(f"OK: inserted {ok} tiles into set '{SET_NAME}' + Default")
        return ok
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Cache Hsinchu QGC Bing Hybrid tiles on board")
    ap.add_argument("--serial", default="", help="adb serial")
    ap.add_argument("--zoom", type=int, default=16, help="single zoom level (default 16)")
    ap.add_argument("--map-id", type=int, default=BING_HYBRID_MAP_ID, help="QGC Bing Hybrid mapId")
    ap.add_argument("--skip-restart", action="store_true", help="do not restart QGC")
    args = ap.parse_args()

    serial = resolve_serial(args.serial)
    print(f"Board: {serial}")
    print(f"Center: Hsinchu {HSINCHU_LAT},{HSINCHU_LON} zoom={args.zoom}")

    # Need board internet for Bing CDN (PC downloads; board only needs push)
    print("Force-stop QGC before rewriting map DB...")
    adb(serial, "shell", f"am force-stop {QGC_PKG}", check=False)
    time.sleep(1)

    owner = get_app_uid(serial)
    print(f"QGC uid: {owner}")

    with tempfile.TemporaryDirectory(prefix="qgc-map-") as td:
        tdir = Path(td)
        db_local = tdir / "qgcMapCache.db"
        ini_local = tdir / "QGroundControl.ini"

        print("Pull map DB + ini...")
        pull_file(serial, MAP_DB_REL, db_local)
        pull_file(serial, INI_REL, ini_local)

        # work on a copy in case download fails mid-way
        db_work = tdir / "qgcMapCache.work.db"
        shutil.copy2(db_local, db_work)

        n = insert_tiles(db_work, args.zoom, args.map_id)
        if n <= 0:
            raise SystemExit("No tiles cached")

        ini_text = ini_local.read_text(encoding="utf-8", errors="replace")
        ini_local.write_text(
            patch_ini(ini_text, HSINCHU_LAT, HSINCHU_LON, float(args.zoom)),
            encoding="utf-8",
        )

        print("Push map DB + ini...")
        push_file(serial, db_work, MAP_DB_REL, owner)
        push_file(serial, ini_local, INI_REL, owner)

    size = adb_shell(serial, f"su 0 stat -c %s {MAP_DB_REL}")
    print(f"Board map cache size: {size} bytes")

    if not args.skip_restart:
        print("Start QGC...")
        adb(
            serial,
            "shell",
            f"am start -n {QGC_PKG}/{QGC_ACTIVITY}",
            check=False,
        )

    print("Done: Hsinchu offline map cache ready (auto-stop).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        print(f"adb/command failed: {err}", file=sys.stderr)
        raise SystemExit(exc.returncode or 1)
