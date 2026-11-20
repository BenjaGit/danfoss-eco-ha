# Foretrukken proxy og kortlægning

## Næste skridt

1. **Se på kortlægningen** (startet 20/11-2026 kl. 18:57 med v1.3.0+benjagit.14): den er færdig,
   når ingen proxy har "…" i tabellen på `/lovelace/termostat-proxy` (`proxy_stats.mapped` er
   true for alle par). Tjek især NUC'en (hci0) pr. termostat.
2. **Ret valg-før-kø** ved næste version (ikke hastende, Benjamin valgte 20/11 at vente):
   `EtrvClient._slot` i ble.py vælger proxy, før den venter på proxyens lås. Hører proxyen
   ikke længere termostaten, når låsen er fri, falder `routed_client_class` tilbage til HA's
   valg, og så kan to termostater forbinde via samme Pi samtidig (ca. hvert 10. forsøg under
   kortlægning). Rettelse: tjek `advert_ages` igen efter låsen er taget, og vælg om, hvis
   proxyen er faldet ud.
3. **Poll-interval:** alle 18 står på 1 min som intensiv test (før 60). De gamle options ligger
   på HA i `/config/danfoss_eco_store_backup_20261120/options_before_1min.json`. Spørg
   Benjamin, hvad det skal ende på, når kortlægningen er færdig.

## Status 20/11 kl. 19:10

- HA kører v1.3.0+benjagit.14 (md5-ens med repoet, 26 filer). Alle 18 står på auto.
- Dashboardet er bygget af homeassistant-agenten (Herdr-agent `homeassistant`).
- Fund: NUC'en er bedst for køkken (17/23), trappeopgang (20/35) og makerspace (12/23).
- bt-proxy-forsøgene på Pi'erne er ikke rørt, men målingen 21/11 kan ikke sammenlignes med
  baseline pr. Pi (proxy-valg, parallelle forbindelser og 1-minuts-interval er ændret).
