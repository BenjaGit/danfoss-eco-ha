# Overnight run with the signal-informed proxy choice (22/11 2026)

v1.3.0+benjagit.20, statistics reset 21/11 23:00:53, read 22/11 10:29. 1-minute polling,
four proxies (bt-proxy-4 in gæsteværelset). Compared with 21/11 15:30–21:20: old mechanism
(.18/.19), three proxies, also started from a reset. The two changes cannot be told apart.

Time between successful reads, from the history of `sensor.*_seneste_aflaesning`, mean of 18:

| | Before | Night |
|---|---|---|
| Reads per hour per thermostat | 9.8 | 19.1 |
| Median gap | 5.7 min | 2.8 min |
| 90th percentile gap | 11.7 min | 6.3 min |
| Mean age of the latest reading | 4.8 min | 2.6 min |
| Share of time the reading is older than 5 min | 35 % | 12 % |
| Share of time older than 15 min | 4.5 % | 1.1 % |

Worse than before: gildesal_vest_midt (mean age 5.4 → 6.4 min, older than 15 min 5 → 11 % of the
time) and gildesal_vest_syd (4.3 → 5.8 min, 2 → 8 %). Both hear no proxy better than -84 dBm.
Best gain: gildesal_nord, 11.1 → 1.3 min, on bt-proxy-4 (208/251, -58 dBm).

Connects per proxy overnight: bt-proxy-1 838/1183 (71 %), bt-proxy-2 378/975 (39 %),
bt-proxy-3 613/1071 (57 %), bt-proxy-4 693/1106 (63 %). Assigned: 8 / 4 / 3 / 3.
