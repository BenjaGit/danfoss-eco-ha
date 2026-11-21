# Foretrukken proxy og kortlægning

## Næste skridt

21/11 kl. 12:56: før-billede gemt, inden Benjamin flytter bt-proxy-3 (op på skabet) og
bt-proxy-2 (teknikrummet): `baseline-2026-11-21-before-move.md` + `.json`. Efter flytningen:
spørg Benjamin, nulstil så statistikken (kræver HA-stop) og sammenlign en lige så lang periode
(2,5 time, 1 minuts poll). Benjamin svarede "Vent" på nulstilling kl. 14:15. Besked fra
bt-proxy-agenten: bt-proxy-2 står på racket siden ca. 13:37 (26 % ok 13:41–14:21, hører ikke
gildesal nord), er væk fra HA siden 14:28 (forkert VLAN), og lægges på kabel og genstartes;
agenten skriver, når den er stabil. bt-proxy-2 stabil på kabel fra 14:42:52.
**Efter-måling startet 21/11 kl. 15:30** (Benjamin sagde ja): statistik nulstillet med HA stoppet
15:28–15:30, kopi af tallene før i `/config/danfoss_eco_store_backup_20261121_after_move/` på HA.
Sammenlign 15:30–17:56 med før-billedet (10:30–12:56); bt-proxy-2's forbindelsesinterval-forsøg
(6/12/200) er væk siden 13:37, og NUC'ens Bluetooth er stadig tændt.
Efter-målingen er lavet (`baseline-2026-11-21-after-move.md`): gildesalen faldt 17–72 point.
Placeringer: Benjamin har låst alle enheder på planen i artifact
https://claude.ai/artifact/8zHRj6Cx9XyqC8XrVpW7XG (kopi: `placements-2026-11-21.json`, [etage, x, y]
i cm, husplanens SVG-koordinater). Afstandsmodel fra målingerne: samme etage ≤5 m ca. 78 %, 5–7 m
58 %, 7–9 m 48 %, 9–12 m 31 %; gennem etagedæk ≤3 m 72 %, 3–5 m 60 %, 5–7 m 32 %, >7 m ca. 5 %.
Anbefaling givet 21/11 aften: en fjerde Pi på gildesalens vestvæg mellem vest nord og vest midt
(kælder, x 390, y 1450); Benjamin har ikke besluttet noget. Poll står stadig på 1 minut.
21/11 kl. 21:24: v1.3.0+benjagit.19 kører (signalsensor pr. termostat pr. scanner, 54 stk.,
`sensor.<område>_radiator_<navn>_signal_bt_proxy_N`, 1 prøve i minuttet, historik i HA's recorder).
Benjamin valgte at beholde 1 minuts poll. Benjamins kritik: forbindelsesraten siden nulstilling er
en dårlig målestok for placering; brug signal (RSSI) til placering, alder på seneste aflæsning til
drift, og et glidende vindue til proxyvalget (de to sidste er ikke lavet). Første matrix kl. 21:28:
bt-proxy-2 hører køkken −73, spisestue −71, trappeopgang −69, men får kun 40–52 % forbindelser;
bt-proxy-1 og -3 får 65–90 % ved samme signal. Mistanke: støj ved racket (AP-Rack 40 cm fra Pi'en,
zigbee-antenne, stålplade). Ikke afprøvet. NUC'ens hci0 blev fjernet fra HA ca. 15:25 den 21/11 (oplyst af
homeassistant-agenten), altså før efter-målingen. Dashboardet /lovelace/termostat-proxy har fra 22:06
en signalmatrix og en graf pr. proxy (homeassistant-agenten). En fjerde Pi, bt-proxy-4, er oprettet
af bt-proxy-agenten og har signalsensorer, men var offline kl. 22:02 (flyttes formentlig). Indeklimatesten sluttede 12:50; genstart kræver stadig et ja hver gang.

Stand 21/11-2026 kl. 10:40: ny kortlægning er startet fra nul med alle rettelser (HA
v1.3.0+benjagit.18, bt-proxy v1.0.3-benjagit.11). Benjamin bad om det, fordi de gamle tal mest
viste proxy-logikkens fejl før 22:50 den 20/11 (fx valgte kontor 1 Gildesalen 23 % frem for
Kontoret 20 %, mens tallene efter rettelserne var 28 % mod 43 %).

- 10:29-10:30: HA stoppet, `proxies` tømt i alle 18 store-filer (68 poster), HA startet.
  Kopi af filerne og options: `/config/danfoss_eco_store_backup_20261121/` på HA.
- 10:3x: poll-interval sat til 1 min på alle 18 via options-flow (før: 10). Alle på auto.
- Indeklimatesten startede samtidig (ca. 10:30); nuc-pve var nede ca. 03:00-08:00 i nat.

1. **Se på kortlægningen** om et par timer: færdig, når `proxy_stats.mapped` er true for alle par
   (ingen "…" på `/lovelace/termostat-proxy`). Sammenlign valgene med de gamle, især kontor 1,
   stue vest, gildesal vest midt og makerspace.
2. **Sæt poll-intervallet ned igen**, når kortlægningen er færdig; Benjamin beslutter værdien
   (10 min kørte i nat, 60 før testen).
3. **Tabt link under opkobling** er største fejl (radioforhold). Idéer, ikke besluttet:
   USB-Bluetooth-dongle eller kablet net på Pi'erne, flytte en Pi.
4. **Småting:** `EtrvClimate` bruger `_attr_temperature_unit` (forældet fra HA 2027.11);
   homeassistant-fanen w5:pH har kun fået svar for .9; .17 og .18 er ikke målt hver for sig.

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

### .16 kører (20/11 22:44)

- Udgivet, installeret (34 filer, md5 ens), HA genstartet 22:44 med Benjamins ja, `installed_version` v1.3.0-benjagit.16, ingen opstartsfejl. Debuglogning er slået fra igen.
- Måling i gang 22:48-23:18 (baggrundsjob): "LUKKET UBRUGT" skal gå mod 0, og not found på bt-proxy-3 skal falde. Sammenlign med 21:54-22:24: 61 % / 62 % / 38 % ok, 5 ubrugte links.
- bt-proxy's egen måling 22:33-23:03 er forstyrret af genstarten 22:44 (Benjamin valgte genstart nu).
- Tilbage: Benjamin beslutter poll-intervallet (1 min nu); `_attr_temperature_unit` er forældet fra HA 2027.11; homeassistant-fanen w5:pH har kun svar for .9.

### .17 (20/11 ca. 23:35)

- Måling af .16, 22:48-23:18: 62 % / 78 % / 72 % ok, 0 ubrugte links, not found 2 i alt. Tre Pi'er giver 5,1 ok/min (4,1 før i aften).
- Fund: en aflæsning tager 2-4 min, mest kø bag proxyens lås (én connect ad gangen, 6-7 termostater pr. proxy). 1 min poll giver derfor ikke flere forsøg end ca. 3 min. Retry-stigen (60..900 s) er EKSTRA forsøg og er ikke årsagen; min første forklaring til Benjamin var forkert og er rettet over for ham.
- .17: ét connect-forsøg pr. aflæsning (`CONNECT_ATTEMPTS = 1`). Udgives nu; genstart kræver Benjamins ja.
- Ikke lavet, foreslået til senere: kø efter hvem der har ventet længst (asyncio.Lock er FIFO).
- .17 udgivet, installeret (34 filer, md5 ens) og HA genstartet 23:27 med Benjamins ja; `installed_version` v1.3.0-benjagit.17, ingen opstartsfejl. Måling 23:31-00:01 i gang (baggrundsjob): sammenlign med .16 (62/78/72 % ok, 5,1 ok/min, 16 af 18 aflæst inden for 5 min).

### .18 (20/11 ca. 23:55)

- Køen pr. proxy er nu efter "længst siden sidste vellykkede aflæsning" (`_Turn` i ble.py) i stedet for ankomst. Udgivet og lagt på HA; genstart kræver Benjamins ja. Genstarten afbryder .17-målingen 23:31-00:01.
- Benjamin bad kl. ca. 23:35 om poll-interval 10 min og afbrød så selve kommandoen, da han bad om køen. IKKE sat endnu (alle 18 står på 1 min): spørg ham sammen med genstarten. Gammel værdi i `/config/danfoss_eco_store_backup_20261120/options_before_1min.json`; scriptet er scratchpad `set_poll_10.py` (options-flow pr. entry, overskriver ikke backuppen).
- Forbehold ved køen: med 1 min poll står en termostat, der aldrig svarer, forrest hver gang og tager op til 40 s af proxyen pr. minut. Med 10 min er det uden betydning.
