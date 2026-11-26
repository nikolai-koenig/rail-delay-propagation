# Data sources: verified facts, assumptions and open questions

Last reviewed: 2026-11-26. Each claim is tagged:

- **Confirmed**: stated by the data provider or a long-standing maintainer of the Open Rail Data community.
- **Community report**: reported by users on the [openraildata-talk](https://groups.google.com/g/openraildata-talk) list, not by the provider.
- **Unverified**: our assumption, to be checked against real data.

The Open Rail Data wiki (wiki.openraildata.com) sits behind a browser check that automated tools can't pass, so wiki pages were not read directly for this review. Re-check them by hand.

## Darwin HSP (Historical Service Performance)

| Topic | Status | Finding |
|---|---|---|
| Coverage | Unverified | Darwin is the passenger-information system, so HSP is expected to be passenger-only. To be checked from the operator codes in real responses. |
| History | Community report | About one year back. |
| Access | Confirmed | Free, via a Rail Data Marketplace (RDM) subscription. Two calls: `serviceMetrics` (lists services between two locations in a time band) and `serviceDetails` (per service). |
| Query semantics | Community report | `from_loc` / `to_loc` are locations the train passes through, not its origin and destination. Time bands must be short at busy locations. ([thread, 2021](https://groups.google.com/g/openraildata-talk/c/eTgzHtFxUGc)) |
| Rate limit | Community report | No published limit (P. Hicks, Jul 2026). Users report about 1 request/s, 429 "Spike Alert" responses, and sustained 429s after about one route-month of downloads. HSP "was never designed for bulk scraping". ([rate limit](https://groups.google.com/g/openraildata-talk/c/WKdjosrpimo), [504s](https://groups.google.com/g/openraildata-talk/c/9DHQQopx-QI)) |
| 504s | Community report | Widespread 504s in Mar 2026; the platform team (RDG/CACI) raised the server timeout to 5 minutes. Clients should use long timeouts and back off. |
| Data quality | Community report | A long-standing maintainer suspects "substantial gaps in data and errors". |
| Cancellations | Community report | Absence from HSP only means "HSP doesn't have details of it". Blank actual times "could mean anything – train not reported, train cancelled, or train diverted". HSP excludes services flagged as deleted. CIF and Darwin "may not be consistent". ([thread, Dec 2025](https://groups.google.com/g/openraildata-talk/c/8gV0y9-XDb4)) |
| Elizabeth line | Unverified | Querying HSP by RDG→PAD may miss Elizabeth line services, possibly because Paddington low level uses a different location code. Test RDG→PAD, TCR, FDS, EAL and HAY. |

**Adopted rule (provisional):** absence or blank actual times is labelled `missing`, never `cancelled`. A service counts as cancelled only when the record carries an explicit cancellation reason. The rule will be refined in `docs/cancellations.md`.

## Alternative to HSP: Darwin Push Port archive

- Community report: a public archive of RDM Darwin Push Port messages from **2025-09-07**, stored as hourly gzip files, at ilovetrains.co.uk. ([thread](https://groups.google.com/g/openraildata-talk/c/yMWGdj3rG2M))
- Push Port messages mark cancellations explicitly. Parsing them is more work than calling HSP.
- Its redistribution licence is **unclear**; check before relying on it.
- Plan: compare it with HSP over one week before choosing the Phase 1 source.
- We also capture the Push Port ourselves (see the collector) from 2026-11 onwards.

## Network Rail TRUST (Train Movements)

| Topic | Status | Finding |
|---|---|---|
| Historical archive | Confirmed | "There isn't a published official set of historical messages" (P. Hicks, Jun 2025). Options: your own collector, private archives, or an FOI request to Network Rail. ([thread](https://groups.google.com/g/openraildata-talk/c/PH0mtnyTCAM), [FOI experience](https://groups.google.com/g/openraildata-talk/c/1SW6ZAdkFTU)) |
| Coverage | Confirmed | Covers all operators, including freight (topic `TRAIN_MVT_ALL_TOC`). Reports are at TRUST reporting points, not every timing point. |
| Access route A | Community report | Network Rail Open Data at `publicdatafeeds.networkrail.co.uk`. STOMP on port 61618. Accounts are approved by hand (can take days); the platform is capped at 1,000 users. ([trackside docs](https://github.com/carbonarok/trackside)) |
| Access route B | Community report | RDM product "NWR Train Movements" over Kafka (SASL_SSL). One consumer group per product. ZScaler or corporate VPNs have broken connections. ([thread](https://groups.google.com/g/openraildata-talk/c/EnZK7vzo_fs)) |
| Licence | Confirmed | Open Government Licence (version not stated). No Network Rail branding; the project may not be called "official". No uptime guarantee. ([licence](https://www.networkrail.co.uk/who-we-are/transparency-and-ethics/transparency/open-data-feeds/network-rail-infrastructure-limited-data-feeds-licence/), [open data page](https://www.networkrail.co.uk/who-we-are/transparency-and-ethics/transparency/open-data-feeds/)) |

## SCHEDULE (CIF) and CORPUS

- Both are available as Network Rail file downloads (authenticated) and as RDM file products.
- The CORPUS download URL used in `rdp reference download-corpus` (`.../ntrod/SupportingFileAuthenticate?type=CORPUS`) comes from community docs. **To verify on first use.**
- CIF contains engineering, pathing and performance allowances per location, which is the direct measure of timetable slack for RQ1.

## Context data

- **Weather: Open-Meteo.** Confirmed: CC BY 4.0 licence; free non-commercial use under 10,000 calls/day. ([terms](https://open-meteo.com/en/terms))
- **Bank holidays: GOV.UK JSON.** Open Government Licence (from prior knowledge; to verify).
- **School terms:** there is no national feed. To be compiled by hand for the local authorities along the corridor.

## Open actions

- [ ] FOI request to Network Rail for one year of TRUST/PSS movements on the corridor (would de-risk RQ2).
- [ ] Ask CACI support about HSP limits for academic use.
- [ ] Read the HSP product licence on RDM when subscribing.
- [ ] Verify the CORPUS URL and the Network Rail STOMP port on first connection.
