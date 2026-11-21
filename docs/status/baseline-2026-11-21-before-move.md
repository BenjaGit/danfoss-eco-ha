# Baseline before the proxies were moved (21/11 2026)

Taken 12:56 local time, covering 10:30–12:56 (statistics were reset to zero at 10:29–10:30).
Integration v1.3.0+benjagit.18, bt-proxy v1.0.3-benjagit.11, poll interval 1 minute, all 18 on auto.
Raw numbers per thermostat: `baseline-2026-11-21-before-move.json`.

Placement during this period: bt-proxy-1 on the shelf in Kontoret, bt-proxy-2 in Gildesalen,
bt-proxy-3 in Stuen (old spot), NUC hci0 in teknikrummet.
Planned change: bt-proxy-3 up on the cabinet in Stuen, bt-proxy-2 into teknikrummet on top of the
rack (ethernet, zigbee antenna moves there), NUC Bluetooth switched off later.

## Home Assistant: successes/attempts per thermostat and scanner

Bold = chosen proxy, * = mapped. 25 of 66 pairs mapped.

| Thermostat | Kontoret (1) | Gildesalen (2) | Stuen (3) | NUC |
|---|---|---|---|---|
| gaestetoilet | 11/20* | **26/35*** | 0/10* | – |
| gaestevaerelse | **22/27*** | 13/21* | 0/10* | – |
| gang | **16/27*** | 4/16 | 5/15 | 0/9 |
| garderobe | **29/34*** | 2/9 | 4/9 | 0/8 |
| gildesal_nord | 7/18 | **30/33*** | 0/8 | – |
| gildesal_vest_midt | 6/16 | **22/29*** | 0/10* | 4/17 |
| gildesal_vest_nord | 7/20* | **30/32*** | – | 0/8 |
| gildesal_vest_syd | 0/9 | **30/36*** | 5/11 | 1/11 |
| koekken | 3/14 | 0/9 | **3/14** | 21/32* |
| kontor_1 | **30/38*** | 3/9 | 1/8 | 0/8 |
| kontor_2 | **29/34*** | 4/11 | 3/10 | 0/4 |
| lager | **19/24*** | 19/29* | – | – |
| makerspace | 0/9 | 4/14 | **9/19** | 19/29* |
| sovevaerelse | 6/15 | **20/36*** | 4/14 | 0/5 |
| spisestue | 1/10 | 0/9 | **25/44*** | 9/18 |
| stue_karnap | 1/15 | 6/15 | **26/31*** | 0/9 |
| stue_vest | 3/11 | 3/11 | **32/45*** | 3/11 |
| trappeopgang | 5/13 | 2/13 | 1/11 | **19/32*** |
| **Total** | 195/354 (55 %) | 218/367 (59 %) | 118/269 (44 %) | 76/201 (38 %) |

## Pi journals: connect requests 10:30–12:56

| Pi | ok | dropped the link | timed out (30 s) | not found | ok share |
|---|---|---|---|---|---|
| bt-proxy-1 | 196 | 73 | 81 | 4 | 55 % of 354 |
| bt-proxy-2 | 222 | 93 | 46 | 9 | 60 % of 370 |
| bt-proxy-3 | 118 | 86 | 52 | 13 | 44 % of 269 |

No link was closed as "connected but unused" in the period.

These shares include the exploring attempts on scanners that hear a thermostat badly, so compare
them with a period that also starts from a reset, not with steady operation.

Note: at the moment of the snapshot køkken and makerspace showed bt-proxy-3 as chosen although the
NUC is their best scanner (66 %); three minutes earlier both were on the NUC. Probably the NUC had
not heard them for 90 seconds just then (not verified).
