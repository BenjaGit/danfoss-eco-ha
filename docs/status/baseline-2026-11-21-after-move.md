# After the proxies were moved (21/11 2026)

Covers 15:30–18:58 local time (statistics reset with HA stopped 15:28–15:30). Compare with
`baseline-2026-11-21-before-move.md` (10:30–12:56). Raw numbers: `baseline-2026-11-21-after-move.json`.

Changed since the baseline: bt-proxy-3 up on the cabinet in Stuen; bt-proxy-2 from Gildesalen to the
top of the rack in teknikrummet, now on ethernet; the NUC's hci0 got no attempts at all in this
period (Bluetooth apparently off, not verified). Same software and 1-minute polling.

## Best scanner per thermostat (at least 10 attempts), before and after

| Thermostat | Before | After | Change (points) |
|---|---|---|---|
| gildesal_nord | bt-proxy-2 30/33 (91 %) | bt-proxy-1 11/57 (19 %) | -72 |
| gildesal_vest_syd | bt-proxy-2 30/36 (83 %) | bt-proxy-2 28/63 (44 %) | -39 |
| gildesal_vest_nord | bt-proxy-2 30/32 (94 %) | bt-proxy-1 23/41 (56 %) | -38 |
| gildesal_vest_midt | bt-proxy-2 22/29 (76 %) | bt-proxy-1 16/27 (59 %) | -17 |
| trappeopgang | hci0 19/32 (59 %) | bt-proxy-2 20/45 (44 %) | -15 |
| koekken | hci0 21/32 (66 %) | bt-proxy-3 18/33 (55 %) | -11 |
| gaestetoilet | bt-proxy-2 26/35 (74 %) | bt-proxy-1 22/34 (65 %) | -10 |
| garderobe | bt-proxy-1 29/34 (85 %) | bt-proxy-1 19/25 (76 %) | -9 |
| stue_vest | bt-proxy-3 32/45 (71 %) | bt-proxy-3 22/35 (63 %) | -8 |
| kontor_1 | bt-proxy-1 30/38 (79 %) | bt-proxy-1 22/31 (71 %) | -8 |
| spisestue | bt-proxy-3 25/44 (57 %) | bt-proxy-3 18/33 (55 %) | -2 |
| kontor_2 | bt-proxy-1 29/34 (85 %) | bt-proxy-1 28/30 (93 %) | +8 |
| gaestevaerelse | bt-proxy-1 22/27 (81 %) | bt-proxy-1 28/31 (90 %) | +9 |
| stue_karnap | bt-proxy-3 26/31 (84 %) | bt-proxy-3 45/48 (94 %) | +10 |
| sovevaerelse | bt-proxy-2 20/36 (56 %) | bt-proxy-1 22/30 (73 %) | +18 |
| gang | bt-proxy-1 16/27 (59 %) | bt-proxy-1 23/29 (79 %) | +20 |
| lager | bt-proxy-1 19/24 (79 %) | bt-proxy-1 25/25 (100 %) | +21 |
| makerspace | hci0 19/29 (66 %) | bt-proxy-3 40/44 (91 %) | +25 |

## Per scanner

| Scanner | Before (HA) | After (HA) | After, Pi journal: ok / dropped / timed out / not found |
|---|---|---|---|
| bt-proxy-1 Kontoret | 195/354 (55 %) | 256/469 (55 %) | 258 / 72 / 135 / 5 |
| bt-proxy-2 | 218/367 (59 %) Gildesalen | 112/344 (33 %) teknikrummet | 112 / 100 / 110 / 22 |
| bt-proxy-3 Stuen | 118/269 (44 %) | 172/361 (48 %) cabinet | 174 / 82 / 90 / 13 |
| NUC hci0 | 76/201 (38 %) | no attempts | – |

Attempts per minute fell from about 8 to about 5.6: eleven thermostats now queue on bt-proxy-1.
