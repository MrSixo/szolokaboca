# Szőlőkabóca Előrejelző

Az amerikai szőlőkabóca (*Scaphoideus titanus*, a **flavescence dorée** aranyszínű
sárgaság fő vektora) lárvakelésének és imágórajzásának **hőösszeg- (degree-day) alapú**
előrejelzése magyar borvidékekre, **OMSZ** állomásadatból.

Önálló, statikus portál — GitHub Pages-en kiszolgálva.

## Pillérek

1. **Előrejelzés** — per-állomás hőösszeg-görbe, becsült stádium-ablakok (N1/N3/imágó), permetezési ablak.
2. **Térkép** — OMSZ állomások stádium szerint színezve + borvidék-réteg (read-only).
3. **Tudástár** — biológia/életciklus, flavescence dorée, védekezés + NÉBIH.

## Modell

- Bázishőmérséklet: **10,1 °C**, biofix: **január 1.**, felső küszöb ~30 °C
- DD-módszer: single-sine (alapértelmezett) / átlag
- ⚠️ A stádium-küszöbök **helyileg kalibrálandók** — az előrejelzés tájékoztató jellegű.

## Szerkezet

```
index.html              Landing — 3 pillér
elorejelzes.html        Előrejelzés oldal
terkep.html             Monitoring-térkép
tudastar.html           Tudástár
css/style.css           Stílus (No-tox-konzisztens)
scripts/                Adat-pipeline (OMSZ degree-day számítás)
.github/workflows/      GitHub Pages deploy
```

## Adatforrás

[OMSZ / HungaroMet Open Data Portal](https://odp.met.hu) — napi állomásadat.

## Licenc

© 2026 Kovács Gergő Péter
