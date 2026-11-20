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

## Hængende forbindelser (20/11 20:45)

- bt-proxy-1 holdt forbindelser til kontor 2 (fra 19:09:52), lager (19:11:02) og gæstetoilet (20:15:44), som aldrig blev lukket. Termostaterne annoncerer ikke imens ("not seen by any Bluetooth adapter/proxy"), kontor 2 lyser konstant rødt.
- Opgave sendt til bt-proxy-agenten (Herdr `bt-proxy`, svar kommer til pane wK:p1): find årsagen på Pi-siden og luk de tre uden genstart, hvis muligt.
- Vores side: `_connect` lukkede ikke forbindelsen, når PIN-skrivningen løb ud eller blev annulleret. Rettet på grenen `fix/close-link-on-pin-timeout` (ikke udgivet, ikke deployet). Udgivelse som .15 kræver HA-genstart: spørg Benjamin.
- Ikke bekræftet, at det var PIN-skrivningen, der udløste de tre: HA's log for tidspunktet er ikke læst (HAOS logger til journalen, ikke til /config).

### Svar fra bt-proxy og HA's log (20/11 ca. 20:50)

- De tre links blev lukket 20:43 med `bluetoothctl disconnect` på bt-proxy-1, uden genstart. Gæstetoilet er aflæst igen 20:45:33; kontor 2 og lager var endnu ikke forbundet igen ved tjekket.
- bt-proxy v1.0.3-benjagit.9 (lukker et link uden GATT-aktivitet efter 60 s) er pushet, IKKE deployet: venter på Benjamins ja i bt-proxy-fanen.
- HA's log: kl. 19:09:46.551 meldte koordinatoren "Error fetching" for kontor 2, samme øjeblik Pi'en startede det forsøg, der lykkedes 19:09:52. HA fik altså en fejl for forsøget og havde ingen klient at lukke; hverken annullering eller PIN-timeout. Rettelsen på `fix/close-link-on-pin-timeout` er derfor ikke årsagen til de tre, kun et lukket hul.
- bt-proxy foreslår også: lad den samlede timeout dække to forsøg à 17 s (ca. 35 s). Ikke gjort.

### .15 (20/11 ca. 22:00)

- Udgivet: lukning ved PIN-timeout/annullering, 40 s ventetid på connect, nyt valg efter køen. Valg-før-kø er dermed rettet.
- Deploy til HA kræver genstart: spørg Benjamin. Efter genstart: md5-tjek, og mål 30 min mod tallene før (40 min før 21:40: bt-proxy-1 197 forsøg/62 ok, -2 180/66, -3 135/34).
- bt-proxy-agenten laver samtidig: connect-grænse 15 -> ca. 30 s og straks-genforsøg ved "dropped the link". Svar kommer til pane wK:p1.
- Poll-interval stadig 1 min; sættes ned efter målingen (Benjamin beslutter værdien).

### .15 kører (20/11 21:50)

- HA genstartet 21:50 med Benjamins ja, `installed_version` v1.3.0-benjagit.15. bt-proxy v1.0.3-benjagit.10 (30 s pr. anmodning, genforsøg efter tabt link) kører på alle tre Pi'er fra 21:48-21:49.
- Måling i gang: 30 min fra ca. 21:56, sammenlignes med 31 % / 37 % / 25 % ok (bt-proxy-1/-2/-3). bt-proxy tæller nu "Connecting to" pr. forsøg, så anmodninger = "Connected to" + "Failed to connect to".
- Derefter: Benjamin beslutter poll-intervallet (står på 1 min).
- Set ved opstart, ikke fra denne ændring: `EtrvClimate` bruger `_attr_temperature_unit`, som holder op med at virke i HA 2027.11.

### .16 under vejs (20/11 ca. 22:45)

- bt-proxy's fund: to connects til samme proxy samtidig fra os. Proxyen tager én ad gangen, den anden venter i dens kø til HA's 40 s er gået, og proxyen forbinder så for ingen (de "unused" links). bt-proxy .11 kører (ét disconnect-svar, venter op til 12 s ved not found).
- Rettelse på grenen `fix/one-connect-per-scanner`: en connect flytter aldrig til HA's valg (fejler i stedet), `RECENT_ADVERT_S` 600 -> 90, optionsteksten rettet. Changelog og manifest står allerede til .16. IKKE udgivet.
- Venter på HA's debuglog (22:25-22:40, baggrundsjob skriver scratchpad `ha_debug.log`) for at bekræfte, at det er flytningen til HA's valg, der giver de to samtidige connects. Derefter: udgiv, installer, spørg Benjamin om genstart, mål 30 min ("unused" skal gå mod 0).
- Bekræftet i HA's debuglog 22:25-22:34: 6 af 95 connects flyttede til HA's valg ("ha" på en navngiven proxy) og overlappede en anden connect på samme proxy, fx køkken 22:26:27 (timeout på hci0, 2. forsøg flyttet til bt-proxy-1 med in_progress=1).
