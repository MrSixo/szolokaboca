#!/usr/bin/env python3
"""OMSZ → Szőlőkabóca Előrejelző statikus adat-pipeline.

Minden OMSZ állomásra kiszámolja a kabóca hőösszeg-idősorát (single-sine + átlag)
és a becsült fejlődési stádiumok ablakát, majd statikus JSON-ba írja:

  data/index.json            — állomáslista a térképhez (id, név, lat, lon, aktuális stádium)
  data/stations/<id>.json    — egy állomás teljes napi DD-idősora + stádium-ablakok

A motor a scaphoideus_omsz.py-ból jön; ez csak orchestrál és JSON-t ír.
GitHub Actions cron futtatja naponta.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scaphoideus_omsz as eng  # noqa: E402

# Tiszta, rövid stádium-kulcsok a JSON-hez (kumulált DD küszöbök, bázis 10,1 °C).
# KALIBRÁLANDÓ alapértékek — lásd KOV-205.
STAGES = {"N1": 180, "N3": 350, "imago": 600}
STAGE_UNCERTAINTY = 0.12  # ±12% → becsült ablak (early/late) a központi dátum köré

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def list_station_numbers() -> list[str]:
    """Az ODP daily/recent könyvtárból kiszedi az összes állomásszámot."""
    with urllib.request.urlopen(f"{eng.ODP_BASE}/", timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    return sorted(set(re.findall(r"HABP_1D_(\d+)_akt\.zip", html)))


def parse_meta(csv_text: str) -> dict:
    """Az állomás meta-fejlécéből név, lat, lon, magasság."""
    for line in csv_text.splitlines():
        if line.startswith("#") and ";" in line and line[1:2].isspace():
            parts = [p.strip() for p in line.lstrip("#").split(";")]
            if len(parts) >= 7 and parts[0].isdigit():
                return {
                    "lat": _f(parts[3]), "lon": _f(parts[4]),
                    "elev": _f(parts[5]), "name": parts[6],
                }
    return {"lat": None, "lon": None, "elev": None, "name": "ismeretlen"}


def _f(token: str):
    try:
        return round(float(token), 4)
    except ValueError:
        return None


def stage_windows(cum_series: list[tuple[str, float]]) -> dict:
    """Stádiumonként early/central/late dátum a küszöb ±bizonytalanság alapján."""
    windows = {}
    for key, thr in STAGES.items():
        lo, hi = thr * (1 - STAGE_UNCERTAINTY), thr * (1 + STAGE_UNCERTAINTY)
        central = _crossing(cum_series, thr)
        windows[key] = {
            "threshold": thr,
            "early": _crossing(cum_series, lo),
            "central": central,
            "late": _crossing(cum_series, hi),
            "reached": central is not None,
        }
    return windows


def _crossing(cum_series, target):
    return next((d for d, c in cum_series if c >= target), None)


def current_stage(windows: dict):
    """A legmagasabb elért stádium kulcsa (vagy None)."""
    reached = [k for k in STAGES if windows[k]["reached"]]
    return reached[-1] if reached else None


def build_station(station: str, year: int) -> dict | None:
    """Egy állomás teljes feldolgozása letöltéstől a kész dict-ig."""
    try:
        csv_text = eng.fetch_station_csv(station)
    except SystemExit:
        return None
    meta = parse_meta(csv_text)
    rows = eng.parse_daily(csv_text, year)
    if not rows or meta["lat"] is None:
        return None

    base, upper = eng.DEFAULT_BASE_TEMP_C, eng.DEFAULT_UPPER_TEMP_C
    sine = eng.accumulate(rows, base, upper, "sine")
    avg = eng.accumulate(rows, base, upper, "avg")

    series = [
        {"date": eng.fmt_date(d), "dd_sine": round(ds, 2), "dd_avg": round(da, 2),
         "cum_sine": round(cs, 1), "cum_avg": round(ca, 1), "is_forecast": False}
        for (d, ds, cs), (_, da, ca) in zip(sine, avg)
    ]
    cum_sine = [(s["date"], s["cum_sine"]) for s in series]
    cum_avg = [(s["date"], s["cum_avg"]) for s in series]
    stages = {"sine": stage_windows(cum_sine), "avg": stage_windows(cum_avg)}

    return {
        "id": int(station), "name": meta["name"],
        "lat": meta["lat"], "lon": meta["lon"], "elev": meta["elev"],
        "year": year, "base_temp": base, "upper_temp": upper,
        "last_date": series[-1]["date"], "series": series, "stages": stages,
        "cum_sine": series[-1]["cum_sine"], "cum_avg": series[-1]["cum_avg"],
    }


def index_entry(st: dict) -> dict:
    return {
        "id": st["id"], "name": st["name"],
        "lat": st["lat"], "lon": st["lon"], "elev": st["elev"],
        "last_date": st["last_date"], "cum_sine": st["cum_sine"], "cum_avg": st["cum_avg"],
        "stage_sine": current_stage(st["stages"]["sine"]),
        "stage_avg": current_stage(st["stages"]["avg"]),
    }


def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--limit", type=int, default=0, help="csak az első N állomás (teszt)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    stations_dir = os.path.join(OUT_DIR, "stations")
    os.makedirs(stations_dir, exist_ok=True)

    numbers = list_station_numbers()
    if args.limit:
        numbers = numbers[:args.limit]
    print(f"{len(numbers)} állomás, év: {args.year}", flush=True)

    index = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(build_station, n, args.year): n for n in numbers}
        for fut in as_completed(futures):
            st = fut.result()
            if st is None:
                continue
            write_json(os.path.join(stations_dir, f"{st['id']}.json"), st)
            index.append(index_entry(st))

    index.sort(key=lambda e: e["name"])
    write_json(os.path.join(OUT_DIR, "index.json"), {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "OMSZ Open Data — odp.met.hu",
        "year": args.year, "base_temp": eng.DEFAULT_BASE_TEMP_C,
        "stages_dd": STAGES, "count": len(index), "stations": index,
    })
    print(f"Kész: {len(index)} állomás kiírva → {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
