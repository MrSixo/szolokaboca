#!/usr/bin/env python3
"""Scaphoideus titanus rajzás-előrejelzés OMSZ napi állomásadatból.

Hőösszeg- (degree-day) alapú fenológiai becslés az amerikai szőlőkabóca
(flavescence dorée vektor) lárvakelésének és imágórajzásának időzítéséhez.

Adatforrás: OMSZ / HungaroMet Open Data Portal (odp.met.hu), napi állomásadat.
Modell alapja: T_base = 10,1 °C, biofix = január 1. (Scaphoideus titanus
poszt-dormancia tojásfejlődési küszöbe, Rigamonti et al. nyomán).

FONTOS: a stádium-küszöbök (DD) helyileg KALIBRÁLANDÓK sárgalap/kopogtatásos
megfigyeléssel — a publikált értékek a DD-módszertől és a téli hidegigénytől
függenek. Lásd STAGE_THRESHOLDS_DD.
"""

import argparse
import io
import math
import sys
import urllib.request
import zipfile

ODP_BASE = "https://odp.met.hu/climate/observations_hungary/daily/recent"
MISSING = -999.0

# --- Modellparaméterek (szakirodalmi alapértékek) ---
DEFAULT_BASE_TEMP_C = 10.1   # alsó fejlődési küszöb, °C
DEFAULT_UPPER_TEMP_C = 30.0  # felső küszöb (fejlődés leáll felette), °C
BIOFIX_MONTH, BIOFIX_DAY = 1, 1  # hőösszeg-akkumuláció kezdete: jan. 1.

# Akkumulált DD küszöbök fejlődési stádiumonként (bázis 10,1 °C, jan. 1-től).
# KALIBRÁLANDÓ alapértékek — induló nagyságrend, helyi megfigyeléssel pontosítandó.
STAGE_THRESHOLDS_DD = {
    "N1 – első lárvák megjelenése (kelés kezdete)": 180,
    "N3 – 3. lárvastádium (1. permetezés ablak)": 350,
    "Imágó – kifejlett egyedek rajzása": 600,
}

# Kényelmi állomáslista (OMSZ-szám = állomásnév, borvidéki relevancia).
KNOWN_STATIONS = {
    "13704": "Sopron Kuruc-domb (Soproni)",
    "13711": "Fertőrákos (Soproni)",
    "36100": "Siófok (Balatoni)",
    "26505": "Keszthely Tanyakereszt (Balaton-felvidéki)",
    "36500": "Iregszemcse (Balatonboglári körzet)",
    "53215": "Eger (Egri)",
    "52744": "Miskolc Diósgyőr (Bükki közelében)",
}


def station_url(station: str) -> str:
    return f"{ODP_BASE}/HABP_1D_{station}_akt.zip"


def fetch_station_csv(station: str) -> str:
    """Letölti és kicsomagolja az állomás napi CSV-jét (ZIP-ből)."""
    try:
        with urllib.request.urlopen(station_url(station), timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SystemExit(f"Hiba: a(z) {station} állomás nem található az ODP-n.")
        raise SystemExit(f"Hiba az állomás letöltésekor ({station}): {exc}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Hálózati hiba: {exc.reason}")
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        return zf.read(csv_name).decode("utf-8", errors="replace")


def parse_station_name(csv_text: str) -> str:
    """A meta-fejlécből kiolvassa az állomás nevét."""
    for line in csv_text.splitlines():
        if line.startswith("#") and ";" in line and line[1:2].isspace():
            parts = [p.strip() for p in line.lstrip("#").split(";")]
            if len(parts) >= 7 and parts[0].isdigit():
                return parts[6]
    return "ismeretlen"


def parse_daily(csv_text: str, year: int) -> list[tuple[str, float, float, float]]:
    """Visszaad (datum_YYYYMMDD, t_mean, t_min, t_max) sorokat az adott évre.

    A nem-numerikus header- és meta-sorokat kihagyja; -999 értéket NaN-ként kezel.
    """
    rows = []
    for line in csv_text.splitlines():
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 9 or not parts[0].isdigit():
            continue  # meta / fejléc / üres sor
        date_str = parts[1]
        if not (date_str.isdigit() and len(date_str) == 8):
            continue
        if int(date_str[:4]) != year:
            continue
        t_mean, t_min, t_max = (_num(parts[i]) for i in (4, 6, 8))
        rows.append((date_str, t_mean, t_min, t_max))
    rows.sort(key=lambda r: r[0])
    return rows


def _num(token: str) -> float:
    try:
        value = float(token)
    except ValueError:
        return math.nan
    return math.nan if value == MISSING else value


def dd_average(t_mean, t_min, t_max, base, upper) -> float:
    """Egyszerű átlag módszer felső küszöb-levágással. Forrás: OMSZ napi középhő (t)."""
    mean = t_mean
    if math.isnan(mean):  # ha nincs napi közép, (min+max)/2 helyettesít
        if math.isnan(t_min) or math.isnan(t_max):
            return math.nan
        mean = (t_min + t_max) / 2
    mean = min(mean, upper)
    return max(0.0, mean - base)


def dd_single_sine(t_mean, t_min, t_max, base, upper) -> float:
    """Baskerville–Emin single sine módszer (alsó küszöb). Pontosabb, ha t_min < base."""
    if math.isnan(t_min) or math.isnan(t_max):
        return dd_average(t_mean, t_min, t_max, base, upper)
    t_max = min(t_max, upper)
    if t_max <= base:
        return 0.0
    if t_min >= base:
        return (t_max + t_min) / 2 - base
    amplitude = (t_max - t_min) / 2
    avg = (t_max + t_min) / 2
    theta = math.asin(max(-1.0, min(1.0, (base - avg) / amplitude)))
    return ((avg - base) * (math.pi / 2 - theta) + amplitude * math.cos(theta)) / math.pi


def accumulate(rows, base, upper, method):
    """Kumulált hőösszeget számol naponta. Visszaad (datum, napi_DD, kumulalt_DD)."""
    dd_fn = dd_single_sine if method == "sine" else dd_average
    cumulative = 0.0
    series = []
    for date_str, t_mean, t_min, t_max in rows:
        daily = dd_fn(t_mean, t_min, t_max, base, upper)
        if not math.isnan(daily):
            cumulative += daily
        series.append((date_str, daily, cumulative))
    return series


def fmt_date(date_str: str) -> str:
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"


def find_stage_dates(series, thresholds):
    """Megkeresi az első napot, amikor a kumulált DD elér egy küszöböt."""
    hits = {}
    for label, target in thresholds.items():
        hit = next((d for d, _, c in series if c >= target), None)
        hits[label] = hit
    return hits


def report(station, name, series, thresholds, base, upper, method):
    if not series:
        raise SystemExit("Nincs adat a kért évre.")
    last_date, _, last_cum = series[-1]
    print(f"\n=== Scaphoideus titanus – rajzás-előrejelzés ===")
    print(f"Állomás:        {station} – {name}")
    print(f"Modell:         T_base={base} °C, T_felső={upper} °C, "
          f"módszer={'single-sine' if method == 'sine' else 'átlag (OMSZ napi közép)'}")
    print(f"Biofix:         {series[0][0][:4]}-01-01")
    print(f"Utolsó adat:    {fmt_date(last_date)}")
    print(f"Kumulált DD:    {round(last_cum)} °C·nap\n")

    print("Fenológiai stádiumok (KALIBRÁLANDÓ küszöbök):")
    for label, target in thresholds.items():
        hit = next((d for d, _, c in series if c >= target), None)
        if hit:
            print(f"  ✓ {label}: ELÉRVE — {fmt_date(hit)} ({target} DD)")
        else:
            remaining = round(target - last_cum)
            print(f"  … {label}: még nincs ({target} DD, hátra ~{remaining} DD)")
    print()


def list_stations():
    print("Ismert (borvidéki) állomások:")
    for num, name in KNOWN_STATIONS.items():
        print(f"  {num}  {name}")
    print(f"\nTeljes lista: {ODP_BASE}/  vagy keresés: --search <név>")


def search_stations(query: str):
    """Élő keresés az ODP állomásai között név alapján (meta-fejlécből)."""
    index_url = f"{ODP_BASE}/"
    with urllib.request.urlopen(index_url, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    import re
    numbers = sorted(set(re.findall(r"HABP_1D_(\d+)_akt\.zip", html)))
    print(f"Keresés '{query}' — {len(numbers)} állomás átvizsgálása...")
    q = query.lower()
    for num in numbers:
        try:
            name = parse_station_name(fetch_station_csv(num))
        except SystemExit:
            continue
        if q in name.lower():
            print(f"  {num}  {name}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--station", default="53215", help="OMSZ állomásszám (alap: 53215 Eger)")
    ap.add_argument("--year", type=int, default=2026, help="vizsgált év (alap: 2026)")
    ap.add_argument("--base-temp", type=float, default=DEFAULT_BASE_TEMP_C)
    ap.add_argument("--upper-temp", type=float, default=DEFAULT_UPPER_TEMP_C)
    ap.add_argument("--method", choices=["avg", "sine"], default="avg",
                    help="DD-módszer: avg (OMSZ napi közép) vagy sine (single-sine)")
    ap.add_argument("--list", action="store_true", help="ismert állomások listája")
    ap.add_argument("--search", metavar="NÉV", help="állomáskeresés név alapján")
    args = ap.parse_args()

    if args.list:
        list_stations()
        return
    if args.search:
        search_stations(args.search)
        return

    csv_text = fetch_station_csv(args.station)
    name = parse_station_name(csv_text)
    rows = parse_daily(csv_text, args.year)
    series = accumulate(rows, args.base_temp, args.upper_temp, args.method)
    report(args.station, name, series, STAGE_THRESHOLDS_DD,
           args.base_temp, args.upper_temp, args.method)


if __name__ == "__main__":
    main()
