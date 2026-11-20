# Foretrukken proxy (bestilt af homeassistant 20/11-2026)

## Næste skridt

1. Vent på Benjamins OK til at stoppe/starte HA (spurgt i panen 20/11 ca. kl. 16:10).
2. Med HA stoppet: læg startværdier ind i `/config/.storage/danfoss_eco.<entry_id>` under
   `data.proxies` (tal fra Pi-journalerne 14/11–20/11 15:45, skaleret til højst 40 forsøg pr.
   par). Skal ske med HA stoppet, ellers overskriver den kørende .7 filen. Scriptet lå i
   sessionens scratchpad (`seed_on_host.py`); det kan genskabes fra forespørgslen i
   `~/GitHub/bt-proxy/docs/status/ble-success-rate.md` grupperet på MAC.
3. Efter start: bekræft i Pi-journalen (VictoriaLogs, `_HOSTNAME:bt-proxy-N "Connecting to"`),
   at mindst to termostater forbindes via den proxy, som forbindelsessensorens attribut `proxy`
   viser med `proxy_choice: learned`.
4. Svar afsenderen: `herdr agent prompt w5:pH "[svar fra danfoss-eco-ha] ..."`. Slet denne fil.

## Gjort

- v1.3.0+benjagit.8 er merget, tagget, udgivet og installeret via HACS; 25 filer md5-ens med
  repoet. HA kører stadig .7, indtil den genstartes.
- Tvangen sker ved at overskrive `_async_get_best_available_backend_and_device` i klient-klassen
  (ble.py `routed_client_class`), afprøvet mod habluetooth 7.1.2.
- Forsøgene på Pi'erne (cache, interval, scan-pause) er ikke rørt.
