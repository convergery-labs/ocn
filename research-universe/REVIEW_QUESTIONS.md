# Universe Company Review — Open Questions

Companies flagged during category-by-category review.
After all 19 categories are reviewed, we'll decide on DB fixes and prompt changes together.

**Format for each category:**
- Flagged companies with status (verified = from Excel, pending = from discovery/agent)
- The specific prompt rule/line that caused the misclassification
- The core question it raises

---
## DB Fixes Applied (local)

The following were cleaned up during the dedup + category-correction pass. DB total: **1,533** companies.

| Company | Action | Notes |
|---------|--------|-------|
| Leonardo S.p.A. (LDO, pending, cat 16) | **Deleted** — renamed canonical entry | "Leonardo" seed was in cat 05 (wrong). Agent entry moved to cat 16 (Defense), renamed to `Leonardo`, ticker `LDO.MI`, promoted to `verified`. |
| Thales Group (HO, pending, cat 16) | **Deleted** — renamed canonical entry | "Thales" seed was in cat 05 (wrong). Agent entry moved to cat 16 (Defense), renamed to `Thales`, ticker `HO.PA`, promoted to `verified`. |
| Fortescue (FMG.AX, verified, cat 19) | **Deleted** — renamed canonical entry | "Fortescue" seed was in cat 19 (wrong). Agent entry `Fortescue Metals Group` in cat 01 (Raw Materials) is correct — renamed to `Fortescue`, ticker `FMG.AX`, promoted to `verified`. |
| ASML Holding N.v (ASML, verified, cat 04) | **Deleted** | Duplicate of `ASML` (ASML.AS). Both were Excel seeds with different ticker formats and slightly different subcategories. `ASML` (ASML.AS) is kept as canonical. |
| Anixter International (AXE, pending, cat 07) | **Deleted** | Acquired by WESCO International in 2020 — no longer an independent company. |

**Dedup logic also fixed** — `_is_duplicate()` in `discovery.py` now handles:
- Variant names that reduce to the same core word after stop-word stripping
- ADR/ADS/SHS/ORD share-class suffixes stripped before comparison
- Ticker base-match via `LIKE base.%` to catch exchange-suffix variants (688256 matches 688256.SS)
- Single-word existing entries no longer block multi-word proposed names (Tencent won't block Tencent Music)

**Taxonomy subcategory parent audit** — 7 subcategories appeared misparented in the UI (showing "currently in wrong category"). Verified against both local and production DB — all 7 are already correctly parented:

| Subcategory | Parent (correct) |
|-------------|-----------------|
| Endpoint Security / AI-Powered Threat Detection | 10. AI Software Infrastructure |
| GPU Cloud / Neocloud | 09. Cloud & Compute Platforms |
| Logistics SaaS / AI | 19. Applications & Digital Economy |
| Automotive / Mobility AI Software | 13. Robotics & Physical AI |
| Asset Management / Quantum Investment | 17. Financial Infrastructure & AI Capital |
| Banking / Quantum Finance | 17. Financial Infrastructure & AI Capital |
| Semicap Components / RF Power | 04. Semiconductor Manufacturing |

The companies under these subcategories (CoreWeave, Nebius, Descartes Systems, KPIT Technologies, Franklin Templeton, Mitsubishi UFJ, Betterment, Wealthfront, Comet Holding, Qorvo, Skyworks, Absolute Security, Lacework, Snyk) are correctly assigned. The companies flagged in the category reviews (Franklin Templeton, MUFG, KPIT, Betterment, Wealthfront) are misclassified at the **company level** — the subcategory parent is fine, but these companies don't belong in those categories at all. See cat 13 and cat 17 review sections.

---

## Category 01 — Raw Materials & Critical Minerals

**Rule updated**: cat 01 now includes ANY company whose primary business is mining, extraction, or processing raw materials from the earth — regardless of whether that mineral feeds the AI stack directly. The old "minerals essential to AI hardware supply chains" test has been removed from the prompt.

| Company | Ticker | Status | Issue | Resolution |
|---------|--------|--------|-------|------------|
| ~~Elite Material~~ | ~~2383.TW~~ | ~~verified~~ | ~~PCB laminate maker — manufactures a fabricated product, not a miner~~ | **FIXED** — moved to cat 04 (IC Substrates / PCB), status → pending_review. |
| ~~Allegheny Technologies~~ | ~~ATI~~ | ~~pending~~ | ~~Specialty alloy processor — primary product is fabricated alloy components~~ | **FIXED** — moved to cat 04 (Advanced Components / Materials), status → pending_review. |
| ~~ArcelorMittal~~ | ~~MT~~ | ~~pending~~ | ~~Steel producer — mines iron ore but primary identity is steel manufacturing~~ | **FIXED** — moved to cat 07 (Construction Materials), status → pending_review. Steel is a fabricated product; data center construction is the closest real use-case in the taxonomy. |
| ~~Nutrien~~ | ~~NTR~~ | ~~pending~~ | ~~Fertilizer/potash — flagged for "no AI stack role"~~ | **RESOLVED** — potash mining is mining. Belongs in cat 01 under new rule. No longer an issue. |
| ~~Mosaic Company~~ | ~~MOS~~ | ~~pending~~ | ~~Fertilizer/potash — same as Nutrien~~ | **RESOLVED** — potash miner. Belongs in cat 01. |
| ~~Belaruskali~~ | ~~Private~~ | ~~pending~~ | ~~Potash — same as Nutrien~~ | **RESOLVED** — potash miner. Belongs in cat 01. |
| ~~K+S AG~~ | ~~KSAG~~ | ~~pending~~ | ~~Potash/salt — same as Nutrien~~ | **RESOLVED** — potash/salt miner. Belongs in cat 01. |
| ~~Intrepid Potash~~ | ~~IPI~~ | ~~pending~~ | ~~Potash — same as Nutrien~~ | **RESOLVED** — potash miner. Belongs in cat 01. |

### Core question for cat 01
> **"The filter is: does the company's primary revenue come from selling the raw or minimally-processed material itself (ore, concentrate, billet, refined metal)?"**
> Potash, salt, agricultural minerals — all fine in cat 01. The old AI-stack test was too narrow.
> **RESOLVED** — the downstream manufacturer question is now settled: Elite Material (PCB laminates) → cat 04, Allegheny Technologies (specialty alloys) → cat 04, ArcelorMittal (structural steel) → cat 07. Prompt updated with explicit CRITICAL DISTINCTION block covering this pattern.

---

## Category 02 — Energy & Grid Infrastructure

All flagged companies resolved. Prompt updated with two CRITICAL EXCLUSION blocks.

| Company | Ticker | Resolution |
|---------|--------|------------|
| ~~Ambiq Micro~~ | ~~AMBQ~~ | **FIXED** → cat 04 (AI Compute / Semiconductors) |
| ~~Wolfspeed~~ | ~~WOLF~~ | **FIXED** → cat 04 (Semicap Equipment / Compound Semi) |
| ~~ON Semiconductor~~ | ~~ON~~ | **FIXED** → cat 04 (AI Compute / Semiconductors) |
| ~~Navitas Semiconductor~~ | ~~NVTS~~ | **FIXED** → cat 04 (AI Compute / Semiconductors) |
| ~~Monolithic Power Systems~~ | ~~MPWR~~ | **FIXED** → cat 04 (AI Compute / Semiconductors) |
| ~~Vicor~~ | ~~VICR~~ | **FIXED** → cat 04 (AI Compute / Semiconductors) |
| ~~ASP Isotopes~~ | ~~ASPI~~ | **FIXED** → cat 03 (Nuclear Power for AI Compute) |
| ~~Encore Energy~~ | ~~EU~~ | **FIXED** → cat 03 (Nuclear Power for AI Compute) |
| ~~Lightbridge~~ | ~~LTBR~~ | **FIXED** → cat 03 (Energy / Nuclear / Power) |
| ~~Nano Nuclear Energy~~ | ~~NNE~~ | **FIXED** → cat 03 (Energy / Nuclear / Power) |
| ~~Uranium Energy~~ | ~~UEC~~ | **FIXED** → cat 03 (Nuclear Power for AI Compute) |
| ~~EQT Corporation~~ | ~~EQT~~ | **FIXED** → cat 01 (Raw Materials — extraction primary) |
| ~~Saudi Aramco~~ | ~~2222.SR~~ | **FIXED** → cat 01 (Raw Materials — extraction primary) |
| ~~Rolls-Royce Holdings~~ | ~~RR.L~~ | **FIXED** → cat 16 (Aerospace / Defense AI — jet engines primary) |

### Prompt fixes applied
> **Pattern 1 - Power semiconductor bleed**: Added CRITICAL EXCLUSION 1 to cat 02 definition — chip/semiconductor makers whose products relate to power (SiC, GaN, PMICs) belong in cat 04. The test is: does the company operate energy infrastructure, or sell chips?
> **Pattern 2 - Fuel/extraction bleed**: Added CRITICAL EXCLUSION 2 — oil, gas, uranium producers sell fuel, they don't operate grid infrastructure. Selling fuel to power plants ≠ cat 02.
> **Cheatsheet updated** with explicit callouts for both patterns.

---

## Category 03 — Nuclear & Advanced Energy

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| ~~Sprott Physical Uranium Trust~~ | ~~U.UN~~ | ~~pending~~ | ~~Investment fund/ETF — not an operating company~~ | **DELETED** — investment fund, excluded by COMMERCIAL_COMPANY_RULE. |
| ~~Plug Power~~ | ~~PLUG~~ | ~~pending~~ | ~~Hydrogen fuel cells — not nuclear or long-duration storage~~ | **FIXED** — moved to cat 02 (Hydrogen / Future Energy). Prompt updated: hydrogen fuel cell makers → cat 02. |
| Energy Vault | NRGV | verified | Gravity-based energy storage — borderline cat 02 vs cat 03 | **KEPT** in cat 03 — gravity-based long-duration storage fits the definition exactly. |
| ~~Electricité de Strasbourg~~ | ~~ELEC~~ | ~~pending~~ | ~~Regional French utility — general electricity, not nuclear-specific~~ | **FIXED** — moved to cat 02 (Energy & Grid). Prompt updated: general utilities with nuclear exposure → cat 02. |
| ~~Vattenfall~~ | ~~Private~~ | ~~pending~~ | ~~Swedish utility — nuclear is one of several sources, not primary~~ | **FIXED** — moved to cat 02 (Energy & Grid). Same rule fix. |
| ~~Fortum~~ | ~~FORTUM~~ | ~~pending~~ | ~~Finnish utility — mix of nuclear + hydro, primarily a utility~~ | **FIXED** — moved to cat 02 (Energy & Grid). Same rule fix. |

### Core question for cat 03
> **"The real filter isn't 'does this company touch nuclear energy?' — it's 'is nuclear or advanced energy their PRIMARY business?'"**
> **RESOLVED (pending fixes applied)** — Vattenfall, Fortum, Electricité de Strasbourg moved to cat 02; Plug Power moved to cat 02. Prompt updated with CRITICAL EXCLUSION blocks for both general utilities with nuclear exposure and hydrogen fuel cell makers.

---

## Category 04 — Semiconductor Manufacturing

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| AIR Products AND Chemicals | APD | verified | Industrial gases supplier to fabs — primary business is chemicals, not semiconductors | From Excel — "does supplying gases to fabs = semiconductor manufacturing?" |
| Linde | LIN | verified | Same as AIR Products — industrial gases, serves many industries beyond semis | From Excel — same question |
| DOW | DOW | verified | Chemicals giant — semiconductor materials is one of many divisions | From Excel — same question |
| Dupont | DD | verified | Chemicals/materials conglomerate — semiconductor is one division | From Excel — same question |
| Celanese | CE | verified | Specialty chemicals — semiconductor use is peripheral | From Excel — same question |
| Eastman Chemical | EMN | verified | Specialty chemicals — semiconductor use is peripheral | From Excel — same question |
| BASF SE | BASFY | pending | Massive chemicals conglomerate — semiconductor chemicals is a tiny division | Rule: "semiconductor materials" is too broad — pulled in any chemicals company with a semi division |
| Hexagon | HEXA-B.ST | verified | Metrology/spatial AI software company — not a chip maker | From Excel — subcategory "Spatial AI / Digital Twin" doesn't belong in cat 04, should be cat 10 AI Software |
| Asustek | 2357.TW | verified | PC/laptop/server assembler — assembles chips, does not make them | From Excel — "AI PCs / Servers" subcategory landed in semiconductor, should be cat 05 Compute Hardware |
| Spirent Communications | SPT.L | verified | Network testing equipment — not semiconductor manufacturing | From Excel — "Network Testing" subcategory landed in cat 04, should be cat 06 Networking |
| Mellanox / NVIDIA (InfiniBand) | NVDA | verified | This is NVIDIA — duplicate issue, NVIDIA appears twice in the DB | DB dedup issue — need to consolidate into one canonical NVIDIA entry |
| Cambricon / Cambricon Technologies | 688256.SS / 688256 | both | Same company, two separate rows — duplicate | Discovery job created a duplicate of a seeded company |
| Maxim Integrated Products | MXIM | pending | Acquired by Analog Devices in 2021 — no longer independent | COMMERCIAL_COMPANY_RULE excludes acquired companies but this slipped through |
| Xilinx Inc | XLNX | pending | Acquired by AMD in 2022 — no longer independent | Same as Maxim — acquired company exclusion not working reliably |
| LTX-Credence Corporation | LTXC | pending | Merged/acquired — no longer independent | Same pattern |

### Core question for cat 04
> **"The real filter isn't 'does this company supply something to semiconductor fabs?' — it's 'is semiconductor design or manufacturing their PRIMARY business?'"**
> Industrial gas and chemicals companies (AIR Products, Linde, DOW, Dupont, BASF, Celanese, Eastman) supply inputs to fabs but serve many other industries — their primary revenue is not semiconductors.
> **Acquired companies** (Maxim, Xilinx, LTX-Credence) keep slipping through despite the exclusion rule — the prompt needs a stronger signal, e.g. "check if the company still trades independently before including it."
> **Duplicate entries** — discovery job is not deduping reliably when company names differ slightly (Cambricon vs Cambricon Technologies, NVIDIA appearing under Mellanox name).

---

## Category 05 — Compute Hardware & Edge Systems

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| Goodman Group | GMG.AX | verified | Real estate/logistics REIT — owns warehouses and data center land | From Excel — "Logistics / Data Center Infra" landed in compute hardware, belongs in cat 07 Data Centers |
| CGI | GIB-A.TO | verified | IT consulting/services — no hardware | From Excel — "AI Services / Systems Integration" is software/services, belongs in cat 10 |
| Reply | REY.MI | verified | IT consulting — same as CGI | From Excel — same question |
| Persistent Systems | PERSISTENT.NS | verified | Digital engineering services — pure software/IT | From Excel — "Digital Engineering / HW-Adjacent" doesn't make it hardware |
| Al Moammar Information Systems | 7200.SR | verified | IT services/reseller — not a hardware manufacturer | From Excel — "IT Infrastructure / AI Services" |
| Globe Telecom | GLO.PS | verified | Philippine telecom operator | From Excel — "Telecom / Edge AI" landed in compute hardware, belongs in cat 08 |
| Nokia | NOKIA.HE | verified | 5G network equipment maker | From Excel — "5G Network Equipment" landed in compute hardware, belongs in cat 06 Networking |
| Fisher & Paykel Healthcare | FPH.NZ | verified | Medical devices company | From Excel — "Healthcare Devices AI" landed in compute hardware, belongs in cat 15 Life Sciences |
| Hyundai Motor | 005380.KS | verified | Car manufacturer — autonomous is a division, cars are primary | From Excel — "Robotics / Autonomous Systems" pulled car companies into compute hardware |
| Volvo Group | VOLV-B.ST | verified | Truck manufacturer — same as Hyundai | From Excel — same question |
| Vingroup | VIC.VN | verified | Vietnamese conglomerate — real estate, retail, EV, many businesses | From Excel — too broad for compute hardware |
| Rheinmetall | RHM.DE | verified | Defense/armaments — primary business is defense, not compute | From Excel — "Defense AI" subcategory landed in compute hardware, belongs in cat 16 |
| Kongsberg Gruppen | KOG.OL | verified | Defense/aerospace systems | From Excel — same as Rheinmetall |
| LIG Nex1 | 079550.KS | verified | Korean defense systems | From Excel — same as Rheinmetall |
| Indra Sistemas | IDR.MC | verified | Spanish defense/IT systems | From Excel — same as Rheinmetall |
| ~~Leonardo~~ | ~~LDO.MI~~ | ~~verified~~ | ~~Italian defense/aerospace~~ | **FIXED** — moved to cat 16 (Defense). Old cat 05 seed deleted; canonical entry is now `Leonardo` (LDO.MI) in cat 16. |
| ~~Thales~~ | ~~HO.PA~~ | ~~verified~~ | ~~French defense/aerospace~~ | **FIXED** — moved to cat 16 (Defense). Old cat 05 seed deleted; canonical entry is now `Thales` (HO.PA) in cat 16. |
| Safran | SAF.PA | verified | French aerospace/defense | From Excel — same as Rheinmetall |
| ST Engineering | S63.SI | verified | Singapore defense/engineering | From Excel — same as Rheinmetall |
| Sparc AI | SPAI.CN | verified | Defense geospatial AI | From Excel — same as Rheinmetall |
| BTQ Technologies | BTQ | verified | Quantum security | From Excel — "Quantum and Advanced Compute" landed in cat 05, belongs in cat 14 |
| Arqit Quantum | ARQQ | verified | Quantum encryption | From Excel — same as BTQ |
| D-Wave Quantum | QBTS | verified | Quantum computers | From Excel — same as BTQ |
| Honeywell Intl INC | HON | verified | Conglomerate — quantum is one small division | From Excel — same as BTQ |
| IBM | IBM | verified | Quantum computing + AI services | From Excel — quantum + HPC landed in cat 05, could be cat 14 or cat 10 |
| IonQ | IONQ | verified | Quantum computers | From Excel — same as BTQ |
| Rigetti Computing | RGTI | verified | Quantum computers | From Excel — same as BTQ |
| Quantum Computing | QUBT | verified | Quantum software/hardware | From Excel — same as BTQ |
| Infleqtion | INFQ | verified | Quantum computing | From Excel — same as BTQ |
| Sealsq | LAES | verified | Quantum cybersecurity | From Excel — same as BTQ |
| Quantum Corporation | QMCO | verified | Data storage — not quantum computing despite the name | From Excel — name confusion, this is a storage company |
| Quantum eMotion | QNC | verified | Quantum random number generation | From Excel — same as BTQ |
| Xanadu Quantum Technologies | XNDU | verified | Quantum computers | From Excel — same as BTQ |
| Oxford Instruments | OXIG.L | verified | Scientific instruments for quantum/semicap | From Excel — quantum instruments landed in cat 05 |
| Horizon Quantum | HQ | verified | Quantum software | From Excel — same as BTQ |
| Qt Group | QTCOM.HE | verified | Developer tools for embedded software — software company | From Excel — "Developer Tools / Embedded Software" is software, belongs in cat 10 |
| Kudelski | KUD.SW | verified | Cybersecurity/digital security | From Excel — "Cybersecurity" landed in compute hardware, belongs in cat 10 |
| WEG | WEGE3.SA | verified | Electrical motors/industrial equipment | From Excel — "Electrical Equipment / Motors" closer to cat 02 Energy/Grid |

### Core questions for cat 05
> **"The real filter isn't 'does this company make something that goes into a compute system?' — it's 'is their PRIMARY product a physical computing device, server, or edge hardware?'"**
> Three big bleed patterns from the Excel original categorisation:
> 1. **Defense companies** (Rheinmetall, Safran, Kongsberg etc.) with "AI" in their product descriptions landed here instead of cat 16 — defense is their primary revenue. Leonardo and Thales have been moved to cat 16.
> 2. **Quantum computing companies** (D-Wave, IonQ, Rigetti, Arqit etc.) landed here under "Advanced Compute" instead of cat 14 Quantum
> 3. **Services/consulting companies** (CGI, Reply, Persistent) landed here because they work with hardware clients — but they sell services not hardware

---

## Category 06 — Networking, Optical & Interconnect

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| **Hoya** | 7741.T | Excel | Makes EUV photomasks for chip lithography — optical materials for semiconductors, not networking | From Excel — "EUV Masks / Optical Materials" subcategory landed here because of the word "optical" in cat 06 name; belongs in cat 04 |
| **F5 Networks** | FFIV | Excel | Application delivery controller / load balancer software — not networking hardware | From Excel — "Load Balancers / CDN" sounds like networking but F5 sells software/services; closer to cat 10 AI Software |
| **Fastly** | FSLY | Excel | CDN / edge cloud platform — pure software service, not optical networking | From Excel — "Load Balancers / CDN" is a software category; Fastly runs a cloud platform, belongs in cat 09 Cloud |
| **Inphi (Marvell)** | MRVL | Excel | Inphi was acquired by Marvell in 2021 — listed here as "Inphi (Marvell)" using Marvell's ticker | From Excel — acquired company still in list; Marvell itself is a cat 04 chip company |
| **Juniper Networks (HPE)** | HPE | Excel | Juniper was acquired by HPE in 2024 — using HPE ticker, not independent anymore | From Excel — acquired company; the entry uses HPE's ticker which is a server/IT company not networking |
| **Intel (Silicon Photonics)** | INTC | Excel | This is Intel as a whole company, labelled for one division — Intel is primarily cat 04 Semiconductor | From Excel — division-level entry; Intel's silicon photonics is one project inside a semiconductor giant |
| **Lumen Technologies** | LUMN | Excel | Long-haul fiber network operator — telecom carrier, not networking equipment maker | From Excel — "Networking / Fiber" subcategory pulled in an operator; Lumen sells connectivity services, belongs in cat 08 Telecom |
| **Sumitomo Electric** | 5802.T | Excel | Japanese conglomerate — wiring, automotive, telecom; shows up in both cat 06 and cat 07 (two subcategories) | From Excel — multi-category entry; fiber cables division is correct for cat 06 but may belong primarily elsewhere |
| ~~**Mellanox Technologies (NVIDIA)**~~ | ~~Private~~ | ~~pending~~ | ~~Acquired by NVIDIA 2020~~ | **DELETED** — acquired, no longer independent. |
| ~~**Oclaro Inc**~~ | ~~Private~~ | ~~pending~~ | ~~Acquired by Lumentum 2019~~ | **DELETED** — acquired. |
| ~~**PMC-Sierra Inc**~~ | ~~Private~~ | ~~pending~~ | ~~Acquired by Microchip 2016~~ | **DELETED** — acquired. |
| ~~**Finisar (II-VI)**~~ | ~~Private~~ | ~~pending~~ | ~~Acquired by II-VI/Coherent 2019~~ | **DELETED** — acquired. |
| ~~**Transmode AB**~~ | ~~Private~~ | ~~pending~~ | ~~Acquired by Infinera 2015~~ | **DELETED** — acquired. |
| ~~**Tellabs Inc**~~ | ~~Private~~ | ~~pending~~ | ~~Defunct/acquired~~ | **DELETED** — defunct. |
| ~~**Radyne Corporation**~~ | ~~Private~~ | ~~pending~~ | ~~Acquired by Comtech 2008~~ | **DELETED** — acquired. |
| ~~**Sycamore Networks**~~ | ~~SCMR~~ | ~~pending~~ | ~~Shell company since 2002~~ | **DELETED** — non-operating shell. |
| ~~**Eoptolink Technology Corporation**~~ | ~~3545~~ | ~~pending~~ | ~~Duplicate of Eoptolink (300502.SZ)~~ | **FIXED** — dedup logic updated. |
| ~~**Proxim Inc / Proxim Wireless**~~ | ~~Private~~ | ~~pending~~ | ~~Two entries for same company~~ | **FIXED** — dedup updated. |
| ~~**Acceris Communications**~~ | ~~Private~~ | ~~pending~~ | ~~Defunct/rebranded telecom~~ | **DELETED** — defunct, no operations. |

### Cat 06 status
All pending items resolved — acquired/defunct companies deleted. Verified companies (Hoya, F5, Fastly, Inphi, Juniper, Intel Silicon Photonics, Lumen, Sumitomo) stay as-is per verified rule. Prompt updated with named acquired company examples in COMMERCIAL_COMPANY_RULE.

---

## Category 07 — Data Centers & Physical Infrastructure

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| **América Móvil** | AMX.MX | Excel | Mexican telecom operator — primary business is mobile/fixed connectivity, not data centers | From Excel — "Mobile Network Operator / LatAm" subcategory belongs in cat 08 Telecom |
| **Advanced Info Service** | ADVANC.BK | Excel | Thai mobile telecom operator | From Excel — "Telecom / Edge" subcategory belongs in cat 08 Telecom |
| **China Mobile** | 0941.HK | Excel | Chinese state telco — data center is one division, telecom is primary | From Excel — "Telecom / Data Centers" subcategory; telco revenue is dominant |
| **China Unicom** | 0762.HK | Excel | Chinese state telco — same as China Mobile | From Excel — same pattern as China Mobile |
| **Cellnex Telecom** | CLNX.MC | Excel | Tower/antenna infrastructure operator — not a data center company | From Excel — "Connectivity Infrastructure" subcategory; Cellnex belongs in cat 08 Telecom (tower ops) |
| **Elisa** | ELISA.HE | Excel | Finnish telecom operator | From Excel — "Telecom / Applied AI" subcategory belongs in cat 08 |
| **Ericsson** | ERIC-B.ST | Excel | 5G/telecom network equipment maker — networking infrastructure, not data centers | From Excel — "Networks / 5G / Edge" subcategory belongs in cat 06 Networking |
| **Ericsson American** | ERIC | Excel | Duplicate of Ericsson above — same company, two rows (Swedish + US ADR tickers) | From Excel — both entries seeded; one is the parent company and one the ADR |
| **du / Emirates Integrated Telecom** | DU.AE | Excel | UAE telecom operator | From Excel — "Telecom / Data Center Connectivity" — telecom operator, cat 08 |
| **NEC** | 6701.T | Excel | Japanese IT conglomerate — AI services, sovereign AI, telecom; data center is one division | From Excel — "AI Services / Sovereign AI / Telecom" is multi-sector; NEC could be cat 10 or cat 16 |
| **NEC Corporation (ADR)** | NIPNF | Excel | Duplicate of NEC above — same company, ADR ticker | From Excel — two rows for same Japanese company |
| **Nemetschek** | NEM.DE | Excel | AEC software / BIM software company — pure software, no hardware | From Excel — "Vertical Software / AEC AI" is a software product; belongs in cat 10 or cat 19 |
| **NTT** | 9432.T | Excel | Japanese telco — IOWN photonics network; telecom is primary | From Excel — "Telecom / Data Centers / IOWN" subcategory; primary revenue is telecom, cat 08 |
| **PLDT** | TEL.PS | Excel | Philippine telecom operator | From Excel — "Telecom / Data Centers" — belongs in cat 08 |
| **Rogers Communications** | RCI-B.TO | Excel | Canadian telecom operator | From Excel — "Data Center Connectivity" — telecom, cat 08 |
| **Singtel** | Z74.SI | Excel | Singaporean telco — data centers is a division | From Excel — "Telecom / Data Centers" — primarily a telecom, cat 08 |
| **stc Group** | 7010.SR | Excel | Saudi telecom operator | From Excel — "Telecom / Cloud / Data Centers" — telecom primary, cat 08 |
| **Telkom Indonesia** | TLKM.JK | Excel | Indonesian state telco | From Excel — same pattern, cat 08 |
| **Telstra** | TLS.AX | Excel | Australian telco | From Excel — "Data Center Connectivity" — belongs in cat 08 |
| **Telus** | T.TO | Excel | Canadian telco | From Excel — "Telecom / Data / AI Services" — belongs in cat 08 |
| **Telephone and Data Systems** | TDS | Excel | US regional telco | From Excel — belongs in cat 08 |
| **Daifuku** | 6383.T | Excel | Warehouse & logistics automation systems — industrial automation, not data center infra | From Excel — "Warehouse & Logistics Automation" subcategory should be cat 13 Robotics or cat 05 |
| **Tata Elxsi** | TATAELXSI.NS | Excel | Embedded software and automotive AI design services — software/services company | From Excel — "Embedded / Automotive AI" is a services business, belongs in cat 10 or cat 19 |
| **Tech Mahindra** | TECHM.NS | Excel | IT/telecom services outsourcing | From Excel — "Telecom AI Services" — pure services company, cat 10 or cat 19 |
| **Coforge** | COFORGE.NS | Excel | IT services company — no hardware or data center infrastructure | From Excel — "Data Center IT Services" sounds like infra but it's a services company |
| **Ecopetrol** | ECOPETROL.CL | Excel | Colombian oil company — primary business is oil extraction | From Excel — "Energy" subcategory in a data center category makes no sense; belongs in cat 01 or cat 02 |
| **Galaxy Digital** | GLXY | Excel | Crypto/digital assets company — not a data center operator | From Excel — "Data Center Physical Infrastructure" subcategory; Galaxy Digital is a financial/crypto company |
| **Iperionx** | IPX | Excel | Titanium materials company — makes specialty metals, not data center infra | From Excel — likely belongs in cat 01 Raw Materials |
| **Luna Innovations** | LUNA | Excel | Fiber optic sensing / materials testing — not a data center company | From Excel — "Data Center Physical Infrastructure" subcategory is too generic |
| **Interdigital** | IDCC | Excel | Wireless standards/licensing IP company — not data center infrastructure | From Excel — "Data Center Physical Infrastructure" catchall subcategory used too broadly |
| **Pure Storage** | PSTG | Excel | All-flash storage arrays — enterprise storage hardware | From Excel — storage hardware belongs in cat 05 Compute Hardware, not data center infra |
| **Netapp** | NTAP | Excel | Enterprise storage and data management — same as Pure Storage | From Excel — storage company, belongs in cat 05 or cat 11 |
| **Fabrinet** | FN | Excel | Contract manufacturer (EMS) for optical/networking components | From Excel — "System Assembly / EMS" subcategory is more cat 05 Compute Hardware |
| **Rittal GmbH & Co. KG** | Private | pending | Duplicate of Rittal below — same German company, two entries | Discovery dedup failed |
| Rittal | Private | pending | Server rack / enclosure maker — only one row exists, no duplicate | **KEPT** — single entry confirmed, legitimate cat 07. |
| Ericsson American | ERIC | Excel | Duplicate of Ericsson | **NOT FOUND** — no separate ADR row in DB, already clean. |
| NEC Corporation (ADR) | NIPNF | Excel | Duplicate of NEC | **NOT FOUND** — no separate ADR row in DB, already clean. |
| ~~**Zenlayer**~~ | ~~Private~~ | ~~pending~~ | ~~Duplicate~~ | **FIXED** — dedup updated. |
| ~~**Zenlayer Asia**~~ | ~~Private~~ | ~~pending~~ | ~~Duplicate~~ | **FIXED** — see above. |
| ~~**Lambda Labs**~~ | ~~Private~~ | ~~pending~~ | ~~GPU cloud misrouted to cat 07~~ | **FIXED** → moved to cat 09 (GPU Cloud / Neocloud). |
| **Cipher Mining** | CIFR | Excel | Crypto mining company — uses data centers but mines Bitcoin | From Excel — "AI Compute Hosting" pulled in Bitcoin mining companies; should be excluded |
| **Hive Digital** | HIVE | Excel | Crypto mining — same as Cipher Mining | Same pattern |
| **Mara Holdings** | MARA | Excel | Crypto mining — same as Cipher Mining | Same pattern |
| **Riot Platforms** | RIOT | Excel | Crypto mining — same as Cipher Mining | Same pattern |
| **Bitdeer** | BTDR | Excel | Crypto mining / HPC hosting | Same pattern — borderline; Bitdeer is moving into AI compute hosting |
| **Terawulf** | WULF | Excel | Crypto/Bitcoin mining using nuclear power | Same pattern |
| **Core Scientific** | CORZ | Excel | Crypto mining / HPC — pivoting toward AI compute | Borderline — transitioning to AI, but primary is crypto mining |

### Core question for cat 07
> **"The real filter isn't 'does this company have anything to do with infrastructure?' — it's 'do they build, own, or operate data center facilities as their PRIMARY business?'"**
> Five big bleed patterns from the original Excel:
> 1. **Telecom operators** (China Mobile, NTT, Singtel, Telstra, Telus, América Móvil, Rogers etc.) with a data center division land here — but their primary revenue is selling connectivity, cat 08.
> 2. **Crypto miners** (Cipher Mining, MARA, RIOT, Hive, Terawulf) land under "AI Compute Hosting" because they use similar GPU-dense infrastructure — but crypto mining ≠ data center colocation.
> 3. **IT/software companies** (Nemetschek, Tata Elxsi, Tech Mahindra, Coforge) land here under generic "Data Center IT Services" or "AI Services" subcategories — they sell software/services not facilities.
> 4. **Storage hardware** (Pure Storage, NetApp) land under "Data Center Physical Infrastructure" — they make storage appliances, not the building/cooling/power of the facility.
> 5. **Duplicate entries** — Ericsson, NEC, and Rittal still appear twice (parent + ADR or slightly different names). Zenlayer duplicates resolved.

---

## Category 08 — Telecom & Connectivity

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| **Accenture** | ACN | Excel | IT consulting / professional services — no network operations | From Excel — "AI Services / Enterprise Transformation" is a consulting subcategory, belongs in cat 10 or cat 19 |
| **Ciena Corporation** | CIEN | Excel | Makes optical networking equipment (switches, transponders) — equipment maker not operator | From Excel — "Fixed Wireless / Backhaul" subcategory; Ciena sells gear, belongs in cat 06 Networking |
| **Nokia** | NOKIA.HE | Excel | 5G/telecom network equipment maker — same as Ciena, sells gear not connectivity | From Excel — "5G Network Equipment" subcategory; Nokia belongs in cat 06 Networking (equipment), not cat 08 (operators) |
| **ZTE Corporation** | 000063.SZ | Excel | Chinese telecom equipment maker — same as Nokia, makes gear | From Excel — "5G Network Equipment" subcategory; belongs in cat 06 Networking |
| Huawei | Private | pending | Telecom equipment maker — verified, stays as-is per verified rule | **KEPT** — verified entry. |
| ~~**Huawei Technologies**~~ | ~~Private~~ | ~~pending~~ | ~~Duplicate of Huawei~~ | **DELETED** — duplicate removed. |
| **FTAI Aviation** | FTAI | Excel | Aircraft leasing / aviation infrastructure — not a telecom company | From Excel — "Industrial AI / Transportation" is a misfit subcategory; FTAI belongs in cat 05 or cat 19 at most |
| **Space42** | SPACE42.AD | Excel | UAE satellite / geospatial AI company — primarily geospatial intelligence, not connectivity | From Excel — "Satellite / Geospatial AI" blurs the line; if satellite internet operator → cat 08, if geospatial analytics → cat 16 or cat 19 |
| **BT Group** | BT-A.L | pending | UK telecom operator — legitimate cat 08 but added via discovery, should be in Excel | Discovery job — this is a major telco that should have been in the original Excel seed |

### Core question for cat 08
> **"The real filter isn't 'does this company work in telecoms?' — it's 'do they sell connectivity (operating a network) as their PRIMARY revenue?'"**
> Two bleed patterns:
> 1. **Equipment makers vs operators**: Nokia, Ciena, ZTE, Huawei make the gear that runs telecom networks — they belong in cat 06 Networking. The distinction is: "do you sell a service subscription (operator) or sell equipment to operators (vendor)?"
> 2. **IT services / consulting** (Accenture) landed here because they serve telecom clients — but serving an industry ≠ being in that industry.

---

## Category 09 — Cloud & Compute Platforms

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| **BCE** | BCE.TO | Excel | Canadian telecom operator — primarily sells phone/internet service | From Excel — "Cloud Connectivity / Networking" subcategory; telecom operator belongs in cat 08 |
| **Bharti Airtel** | BHARTIARTL.NS | Excel | Indian telecom operator | From Excel — "Connectivity / Edge" subcategory; belongs in cat 08 |
| **China Telecom** | 0728.HK | Excel | Chinese state telco | From Excel — "Telecom / Cloud" subcategory; telecom is primary revenue, cat 08 |
| **e& / Emirates Telecommunications Group** | EAND.AE | Excel | UAE telco — two entries (EAND.AE and EAND.AD) for same company | From Excel — duplicate entries with same ticker prefix; telecom operator, cat 08 |
| **e& / Etisalat** | EAND.AD | Excel | Duplicate of e& above | Same |
| **Reliance Industries** | RELIANCE.NS | Excel | Indian conglomerate — oil & gas + telecom + retail + tech | From Excel — "Platform / Telecom / Data"; Jio is the cloud/telecom arm but Reliance primary is petrochemicals/energy |
| **True Corporation** | TRUE.BK | Excel | Thai telecom operator | From Excel — "Telecom / Consumer AI"; telecom operator, cat 08 |
| **Telekom Malaysia** | 4863.KL | Excel | Malaysian telco | From Excel — "Connectivity / Cloud"; cat 08 |
| **Spark New Zealand** | SPK.NZ | Excel | NZ telecom | From Excel — "Connectivity / Cloud"; cat 08 |
| **Telefônica Brasil** | VIVT3.SA | Excel | Brazilian telco (Vivo brand) | From Excel — "Cloud Connectivity / Networking"; cat 08 |
| **ZTE** | 0763.HK | Excel | ZTE appears here AND in cat 08 — duplicate entry across categories; ZTE makes networking equipment | From Excel — second ZTE entry; equipment maker belongs in cat 06 |
| **Futu Holdings** | FUTU | Excel | Online brokerage / fintech platform — not a cloud company | From Excel — "Cloud-Native SaaS / Agentic Platforms" is too broad; Futu is a trading app, cat 17 or cat 19 |
| **Intuitive Surgical** | ISRG | Excel | Surgical robotics — makes the da Vinci robot | From Excel — "Physical AI / Robotics / Healthcare" pulled in a medical robotics company; belongs in cat 13 Robotics or cat 15 Life Sciences |
| **Hut 8 Corp** | HUT | Excel | Bitcoin mining / pivoting to AI compute hosting | From Excel — "AI Compute / Bitcoin-to-AI Pivot" — primary business is still crypto mining |
| **IREN** | IREN | Excel | Crypto mining / AI compute hosting | From Excel — same as Hut 8; borderline if AI hosting revenue is primary |
| **HCLTech** | HCLTECH.NS | Excel | IT services/outsourcing company — sells software services | From Excel — "AI Services / Enterprise" is a services category; belongs in cat 10 or cat 19 |
| **NTT Data** | 9613.T | Excel | IT services subsidiary of NTT | From Excel — "AI Services / IT" is pure services; belongs in cat 10 or cat 19 |
| **Samsung SDS** | 018260.KS | Excel | IT services arm of Samsung | From Excel — "AI Services / Enterprise"; services company, cat 10 or cat 19 |
| **Uber Technologies** | UBER | Excel | Ride-hailing / delivery platform — not a cloud provider | From Excel — "Cloud-Native SaaS / Agentic Platforms" is too broad; Uber is cat 19 Applications |
| **Xero** | XRO.AX | Excel | Accounting SaaS — pure software application | From Excel — "SaaS / Accounting AI"; belongs in cat 19 Applications |
| **Sinch** | SINCH.ST | Excel | CPaaS / SMS/voice API platform — communications infrastructure | From Excel — "CPaaS / Conversational AI" is borderline cat 10 or cat 19; not cloud IaaS/PaaS |
| **Megaport** | MP1.AX | Excel | Network-as-a-Service / cloud connectivity platform | From Excel — "Cloud Connectivity / Network-as-a-Service" is closer to cat 06 Networking than cloud IaaS |

### Core question for cat 09
> **"The real filter isn't 'does this company use cloud or sell anything over the internet?' — it's 'do they sell IaaS/PaaS/GPU cloud compute as their PRIMARY product?'"**
> Three bleed patterns:
> 1. **Telecom operators** (BCE, Airtel, China Telecom, True Corp, Telekom Malaysia, Spark NZ) with a cloud offering land here — their primary revenue is connectivity subscriptions, not cloud compute.
> 2. **SaaS applications** (Xero, Futu, Uber) land under "Cloud-Native SaaS" — being delivered via cloud ≠ selling cloud infrastructure. These are end-user applications, cat 19.
> 3. **IT services companies** (HCLTech, NTT Data, Samsung SDS) land under "AI Services" — they sell labour/consulting, not cloud compute capacity.

---

## Category 10 — AI Software Infrastructure

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| **Adobe** | ADBE | Excel | Creative software suite (Photoshop, Acrobat) — end-user application | From Excel — "AI Applications / SaaS / Agentic Tools" subcategory is too broad; Adobe is cat 19 Applications |
| **Airbnb** | ABNB | Excel | Vacation rental marketplace — consumer application | From Excel — same subcategory; Airbnb is cat 19 |
| **Apple** | AAPL | Excel | Consumer hardware + iOS ecosystem — not AI software infrastructure | From Excel — Apple makes devices (cat 05) and apps (cat 19); it is not MLOps/AI middleware |
| **Meta Platforms** | META | Excel | Social media / consumer apps | From Excel — "AI Applications / SaaS / Agentic Tools" pulled in consumer platforms; cat 19 or cat 12 |
| **Booking Holdings** | BKNG | Excel | Travel booking platform — consumer app | From Excel — cat 19 Applications |
| **Uber Technologies** | UBER | Excel | Ride-hailing — already flagged in cat 09, now also here | From Excel — appears in both cat 09 and cat 10; should be cat 19 |
| **Spotify** | SPOT | Excel | Music streaming — consumer application | From Excel — cat 19 |
| **Duolingo** | DUOL | Excel | Language learning app — consumer application | From Excel — cat 19 |
| **Reddit** | RDDT | Excel | Social news platform | From Excel — cat 19 |
| **Dropbox** | DBX | Excel | File sync/storage — productivity SaaS | From Excel — borderline cat 10 or cat 19; not AI infrastructure |
| **Box** | BOX | Excel | Enterprise file storage — similar to Dropbox | From Excel — same question |
| **Figma** | FIG | Excel | Design tool — end-user software application | From Excel — cat 19 Applications |
| **Docusign** | DOCU | Excel | eSignature platform | From Excel — cat 19 |
| **Fiverr International** | FVRR | Excel | Freelance marketplace | From Excel — cat 19 |
| **Take-Two Interactive** | TTWO | Excel | Video game publisher | From Excel — "AI Applications" pulled in gaming; cat 19 |
| **Shopify** | SHOP | Excel | eCommerce platform | From Excel — cat 19 |
| **Paypal** | PYPL | Excel | Payments platform — financial services, not AI infrastructure | From Excel — cat 17 Financial Infrastructure or cat 19 |
| **SEA Limited** | SE | Excel | Gaming + eCommerce + fintech conglomerate | From Excel — cat 19 |
| **JD.com** | 9618.HK | Excel | Chinese eCommerce/logistics | From Excel — cat 19 |
| **Meituan** | 3690.HK | Excel | Chinese food delivery / local services platform | From Excel — cat 19 |
| **Capgemini** | CAP.PA | Excel | IT consulting / implementation services | From Excel — "AI Services / Implementation" is consulting, not software infrastructure; cat 19 or standalone |
| **Infosys** | INFY.NS | verified | IT services outsourcing | From Excel — "Applied AI Software" is a services label; Infosys sells labour, not software product |
| ~~**Infosys Limited**~~ | ~~INFY~~ | ~~Excel~~ | ~~Duplicate of Infosys (INFY.NS)~~ | **FIXED** — ADR duplicate deleted. One entry remains (`Infosys`, INFY.NS). |
| **Wipro** | WIT | Excel | IT services | From Excel — same as Infosys |
| **Tata Consultancy Services** | TCS.NS | Excel | IT services | From Excel — same as Infosys |
| **Siemens** | SIE.DE | Excel | Industrial conglomerate — automation, energy, transport | From Excel — "Industrial AI / Digital Twin" is one Siemens division; the company is a conglomerate, not AI software infra |
| **SoftBank Group** | 9984.T | Excel | Investment conglomerate — primarily an investor/telco | From Excel — "AI Capital / Platforms" is an investment thesis, not a product; cat 17 |
| **Prosus** | PRX.AS | Excel | Investment/tech holding company | From Excel — "AI Platforms / Capital" is an investor; cat 17 or exclude as holding company |
| **HKEX** | 0388.HK | Excel | Hong Kong stock exchange — financial market operator | From Excel — "Capital Markets Layer" belongs in cat 17 Financial Infrastructure |
| **Globalstar** | GSAT | Excel | Satellite network operator — connectivity, not AI software | From Excel — "AI Infrastructure Software Layer" subcategory used as a catch-all |
| **Viasat** | VSAT | Excel | Satellite connectivity services | From Excel — same; belongs in cat 08 Telecom |
| **Novonesis** | NSIS-B.CO | Excel | Enzyme/biotech company — industrial biotech | From Excel — "Bioindustrial AI / Applied AI" stretched the definition; closer to cat 15 Life Sciences |
| ~~**Runwayml / Runway ML**~~ | ~~Private~~ | ~~pending~~ | ~~Two entries for same company~~ | **FIXED** — dedup concat-strip now catches "RunwayML" == "Runway ML" after stripping spaces. One entry remains (name: `Runway ML`). Category placement (cat 10 vs cat 12) still open. |
| **Hugging Face** | Private | pending | ~~Three entries~~ — duplicates resolved, one entry remains in cat 10 | **Dedup fixed.** One row remains (`pending_review`, cat 10). Category placement still open — Hugging Face is a model hub, closer to cat 12. |
| **Scale AI** | Private | pending | Data labelling platform — belongs in cat 11 AI Data Infrastructure, not cat 10 | Discovery job — "AI Infrastructure Software Layer" is too generic |

### Core question for cat 10
> **"The real filter isn't 'does this company use AI in their software?' — it's 'do they sell AI development/deployment infrastructure (MLOps, vector DBs, AI security, orchestration) as their PRIMARY product?'"**
> Two massive bleed patterns from the original Excel:
> 1. **Consumer/end-user SaaS applications** (Adobe, Airbnb, Spotify, Shopify, Uber, Duolingo, Booking, Reddit, Figma, Docusign) all landed under "AI Applications / SaaS / Agentic Tools" — this subcategory name was too broad. These are cat 19 Applications, not AI infrastructure.
> 2. **IT services / consulting** (Infosys, Wipro, TCS, Capgemini) landed under "Applied AI Software" or "AI Services" — they sell professional services, not software products. No clear home in the taxonomy; closest is cat 19 or a new "IT Services" category. Infosys ADR duplicate resolved — one entry remains.
> Also note: **Runway ML** and **Hugging Face** duplicates both resolved (dedup fix). One entry each remains. Category placement for both still open — both are closer to cat 12 (model providers) than cat 10.

---

## Category 11 — AI Data Infrastructure

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| ~~**SAP**~~ | ~~SAP.DE~~ | ~~Excel~~ | ~~Duplicate of SAP SE~~ | **FIXED** — SAP (SAP.DE) duplicate deleted. One entry remains (`SAP SE`, SAP ticker, cat 10). Category placement still open — SAP is ERP software, not AI data infra. |
| **SAP SE** | SAP | verified | Enterprise ERP/software conglomerate — not AI data infra | From Excel — "Enterprise AI / Data Layer" subcategory; SAP is primarily ERP software (cat 10 or cat 19). |
| **FactSet Research** | FDS | Excel | Financial data terminal / analytics | From Excel — "Data Marketplace / Licensing" is a financial data business; closer to cat 17 Financial Infrastructure |
| **Dun & Bradstreet** | DNB | Excel | Business data / credit risk information | From Excel — "Data Marketplace / Licensing"; primarily a financial/credit data company, cat 17 |
| **Refinitiv (LSEG)** | LSEG.L | Excel | Financial market data — acquired by LSEG in 2021; LSEG is a stock exchange operator | From Excel — "Data Marketplace / Licensing"; financial data belongs in cat 17; also note the company is now LSEG not Refinitiv |
| **RELX** | REL.L | Excel | Publishing / legal / scientific information services | From Excel — "Data / Legal / Risk AI"; RELX is primarily a publishing conglomerate (LexisNexis, Elsevier), not AI data infra |
| **Worldline** | WLN.PA | Excel | Payment processing company | From Excel — "Fintech Data Infrastructure"; payments belong in cat 17 Financial Infrastructure, not AI data |
| **Databricks** | Private | verified | Legitimate cat 11 — `agent_added = true`, `status = verified` means a user manually reviewed and confirmed it | Correct behaviour. No issue. |

### Core question for cat 11
> **"The real filter isn't 'does this company work with data?' — it's 'do they sell tools specifically for AI data pipelines, labelling, annotation, or training data quality?'"**
> The main bleed pattern here:
> 1. **Financial data companies** (FactSet, Dun & Bradstreet, Refinitiv/LSEG, Worldline) land under "Data Marketplace / Licensing" — but they sell financial market data, not AI training data. They belong in cat 17 Financial Infrastructure.
> 2. **General data/ERP platforms** (SAP) land under "Enterprise AI / Data Layer" — SAP is a software suite company, not an AI data infrastructure specialist.
> Cat 11 is otherwise relatively clean — most companies are legitimate AI data tooling (Appen, Snowflake, dbt Labs, Airbyte, labelling tools etc.).

---

## Category 12 — AI Models & Intelligence Layer

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| ~~**Abnormal Security**~~ | ~~Private~~ | ~~pending~~ | ~~AI-powered email security — cybersecurity product, not a model provider~~ | **FIXED** — moved to cat 10 (AI Software Infra). Prompt updated: AI-powered security products → cat 10. |
| **Darktrace** | DARK.L | Excel | AI cybersecurity company — sells a security product | From Excel — "AI Cybersecurity" subcategory; Darktrace uses AI but sells security software, cat 10 |
| ~~**Netskope**~~ | ~~NTSK~~ | ~~pending~~ | ~~Cloud security platform~~ | **FIXED** — moved to cat 10 (AI Software Infra). Same rule fix. |
| ~~**Copy.ai**~~ | ~~Private~~ | ~~pending~~ | ~~AI writing assistant — end-user application~~ | **FIXED** — moved to cat 19 (Applications). Prompt updated: AI apps built on top of models → cat 19. |
| **Jasper / Jasper (formerly Jarvis)** | Private | pending | Two entries for same company — AI marketing copy tool | Jasper already in cat 19 (correct). Dedup issue (two rows) still open. |
| ~~**Character.AI**~~ | ~~Private~~ | ~~pending~~ | ~~Consumer AI chatbot — application layer~~ | **FIXED** — moved to cat 19 (Applications). |
| ~~**Synthesia**~~ | ~~Private~~ | ~~pending~~ | ~~AI video avatar / synthetic video — application~~ | **FIXED** — moved to cat 19 (Applications). |
| ~~**Perplexity AI**~~ | ~~Private~~ | ~~pending~~ | ~~AI search engine — application layer~~ | **FIXED** — moved to cat 19 (Applications). |
| **Tencent Cloud** | 0700.HK | pending | Cloud arm of Tencent — IaaS/PaaS provider | Discovery — Tencent Cloud is a cloud provider (cat 09); the 0700.HK ticker is Tencent Group, not cloud specifically |
| ~~**Test Corp**~~ | ~~TEST~~ | ~~verified~~ | ~~Test/seed entry~~ | **FIXED** — deleted. |
| ~~**Anthropic (Claude API)**~~ | ~~Private~~ | ~~pending~~ | ~~Duplicate of Anthropic~~ | **FIXED** — only one Anthropic row remains. |

### Core question for cat 12
> **"The real filter isn't 'does this company use AI models?' — it's 'do they train and sell foundation models or LLM APIs as their PRIMARY commercial product?'"**
> **RESOLVED (pending fixes applied)** — Abnormal Security and Netskope moved to cat 10; Copy.ai, Character.AI, Synthesia, Perplexity AI moved to cat 19. Prompt updated with CRITICAL EXCLUSION blocks for both patterns.
> Darktrace (Excel/verified) and Jasper dedup issue still open — not pending, requires separate verified-company review.

---

## Category 13 — Robotics & Physical AI

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| **BYD Company** | BYDDY | Excel | EV manufacturer — makes cars, not robots | From Excel — "EV Manufacturer" subcategory; BYD primary business is electric vehicles, cat 19 or a standalone EV category |
| **CATL** | 300750.SZ | Excel | EV battery cell manufacturer — makes batteries, not robots | From Excel — "EV Battery / Cell Manufacturing" subcategory; CATL is a battery company, closer to cat 01 (materials) or cat 04 (manufacturing) |
| **QuantumScape** | QS | Excel | Solid-state battery maker | From Excel — "EV Battery / Cell Manufacturing"; battery R&D company, could be cat 03 Advanced Energy |
| **Solid Power** | SLDP | Excel | Solid-state battery developer | From Excel — same as QuantumScape |
| **Panasonic (EV Battery)** | 6752.T | Excel | Consumer electronics + EV battery — conglomerate | From Excel — "EV Battery / Cell Manufacturing"; Panasonic primary is consumer electronics, not robotics |
| **Rivian** | RIVN | Excel | EV truck/SUV manufacturer | From Excel — "EV Manufacturer"; Rivian makes electric vehicles, not robots |
| **Lucid Group** | LCID | Excel | EV manufacturer | From Excel — same as Rivian |
| **Tesla** | TSLA | Excel | EV + energy + Optimus robot | From Excel — "EV Manufacturer" subcategory; Tesla is multi-category (EVs, energy, robotics, AI); the robotics angle is real but EV is primary |
| **Volkswagen (EV/Software)** | VWAGY | Excel | Car manufacturer — EV is one segment | From Excel — "EV Manufacturer"; VW is primarily a car company, the EV/software angle doesn't make it a robotics company |
| **Altair Engineering** | ALTR | Excel | Simulation/CAE software — pure software company | From Excel — "Digital Twin / Robotics Simulation"; simulation software belongs in cat 10 AI Software, not physical robotics |
| **Ansys** | ANSS | Excel | Simulation software | From Excel — same as Altair; cat 10 AI Software |
| **Aspen Technology** | AZPN | Excel | Industrial process simulation software | From Excel — same pattern; simulation software, cat 10 |
| **UiPath** | PATH | Excel | RPA / workflow automation software | From Excel — "Agentic AI / Automation"; UiPath is a software automation company (cat 10), not physical robotics |
| **Kratos Defense** | KTOS | Excel | Defense drones / unmanned systems | From Excel — "Physical AI / Robotics / Drones"; primary revenue is defense, belongs in cat 16 Defense |
| **Ondas** | ONDS | Excel | Defense/railroad drones | From Excel — same as Kratos; defense application is primary |
| **Unusual Machines** | UMAC | Excel | FPV drones / drone parts | From Excel — "Physical AI / Robotics / Drones"; drone component supplier closer to cat 05 or cat 16 depending on customer mix |
| **Green Hills Software** | GHSI | Excel | RTOS / embedded safety software — pure software | From Excel — "Autonomous Vehicle OS"; operating system software belongs in cat 10 |
| **KPIT Technologies** | KPITTECH.NS | Excel | Automotive software services | From Excel — "Automotive / Mobility AI Software"; IT services company, not robotics hardware |

### Core question for cat 13
> **"The real filter isn't 'does this company involve physical machines or EVs?' — it's 'is their PRIMARY commercial product a physical robot, autonomous system, or drone?'"**
> Two big bleed patterns:
> 1. **EV companies** (BYD, Rivian, Lucid, VW, Tesla, CATL, Panasonic battery) landed under "EV Manufacturer / EV Battery" subcategories — electric vehicles and batteries are not robots. EV is a separate sector that sits across cat 02 (charging/grid), cat 04 (chips), and possibly a new EV category.
> 2. **Simulation/software** (Ansys, Altair, Aspen, UiPath) landed under "Digital Twin / Robotics Simulation" — simulation software belongs in cat 10, not with physical robotics hardware.

---

## Category 14 — Quantum Computing & Sensing

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| ~~**Atom Computing / Atom Optics**~~ | ~~Private~~ | ~~pending~~ | ~~Two entries for same company~~ | **FIXED** — Atom Optics deleted. One row remains (Atom Computing). |
| Quantinuum | Private | pending | Duplicate check | **CONFIRMED** — only one row exists, no duplicate. Legitimate cat 14. |
| ~~**Qu & Co / Qu & Co Technologies**~~ | ~~Private~~ | ~~pending~~ | ~~Two entries for same company~~ | **FIXED** — Qu & Co Technologies deleted. One row remains (Qu & Co). |
| ~~**Rigetti Aspen-M**~~ | ~~Private~~ | ~~pending~~ | ~~Product/chip name, not a company~~ | **FIXED** — deleted. |
| ~~**NTT Corporation**~~ | ~~NTTYY~~ | ~~pending~~ | ~~Japanese telco — quantum is one lab, primary = telecom~~ | **FIXED** — deleted. |
| **Toshiba (Quantum Division)** | 6502.T | Excel | Toshiba is a conglomerate — quantum communications is one division | From Excel — "Quantum Networking / QKD"; Toshiba primary is industrial/electronics, not quantum |
| ~~**Zapata Computing**~~ | ~~Private~~ | ~~pending~~ | ~~Went bankrupt/ceased operations in 2023~~ | **FIXED** — deleted. |

### Core question for cat 14
> **"The real filter isn't 'does this company have a quantum project?' — it's 'is quantum computing or sensing their PRIMARY commercial business?'"**
> Two patterns:
> 1. **Division-level entries** — Toshiba, NTT appear because they have quantum research labs, but their primary business is conglomerate/telecom. The rule "companies whose quantum involvement is limited to a single research program" is in the definition but discovery still includes them.
> 2. **Duplicate entries** — discovery job repeatedly creates 2-3 rows per company when names vary slightly (Atom Computing / Atom Computing Holdings, Quantinuum / Quantinuum Holdings, Qu & Co / Qu & Co Technologies). Dedup is not handling alternate name formats.

---

## Category 15 — Life Sciences & Healthcare AI

All pending items resolved. Rule changed: "uses AI meaningfully" is now the inclusion bar (not "sells AI as a product"). All pharma and health insurers stay in cat 15.

| Company | Resolution |
|---------|------------|
| AbbVie, Amgen, AstraZeneca, Bayer, BMS, Eli Lilly, Gilead, GSK, J&J, Merck & Co, Merck KGaA, Moderna, Novartis, Novo Nordisk, Pfizer, Regeneron, Roche, Sanofi, Vertex | **KEPT** — use AI meaningfully in drug discovery R&D pipelines |
| CVS Health, Elevance, Humana, UnitedHealth | **KEPT** — use AI meaningfully in claims, care management, diagnostics |
| Medtronic, Hologic, Astellas, Alnylam | **KEPT** — use AI meaningfully in medical devices / biologics |
| ~~Zymergen~~ | **DELETED** — acquired by Ginkgo Bioworks 2021, no longer independent |

### Prompt fix applied
> Rule updated in cat 15 definition and cheatsheet: inclusion bar is now "uses AI meaningfully as part of core business" — not "sells AI as a product". Large pharma and health insurers explicitly included.

---

## Category 16 — Defense, Aerospace & Sovereign AI

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| **Baidu** | 9888.HK | Excel | Chinese internet/AI company — consumer search, cloud, autonomous driving | From Excel — "National AI Champion / China" subcategory; Baidu is primarily a tech/AI company (cat 12 or cat 09), not defense |
| ~~**Megvii Technology**~~ | ~~Private~~ | ~~pending~~ | ~~Chinese computer vision / AI — sells to commercial and government~~ | **FIXED** — moved to cat 12 (AI Models & Intelligence Layer). Surveillance AI ≠ defense primary. |
| **SenseTime** | 0020 | pending | Chinese AI — face recognition, autonomous driving | Discovery — same pattern; SenseTime is closer to cat 12 or cat 19 |
| **Tokyo Electron** | 8035.JP | Excel | Japanese semiconductor equipment maker — appears in cat 04 already | From Excel — "Export Controls / Trade Policy" subcategory is a policy angle not a company role; TEL is cat 04 |
| **Virgin Galactic** | SPCE | verified | Commercial space tourism — not defense primary | From Excel — "Aerospace"; Virgin Galactic is consumer space tourism, closer to cat 19 |
| **Sievert Larson / SGBX** | SGBX | Excel | Modular building / construction company — SteelTech not defense | From Excel — "Secure Communications / Government AI" is a misassignment; SGBX (SG Blocks) makes modular containers |
| ~~**Global X Defense ETF**~~ | ~~SHLD~~ | ~~pending~~ | ~~ETF~~ | **DELETED** — investment fund, not an operating company. |
| ~~**Invesco A&D ETF**~~ | ~~PPA~~ | ~~pending~~ | ~~ETF~~ | **DELETED** — same. |
| ~~**iShares US A&D ETF**~~ | ~~ITA~~ | ~~pending~~ | ~~ETF~~ | **DELETED** — same. |
| ~~**SPDR S&P A&D ETF**~~ | ~~XAR~~ | ~~pending~~ | ~~ETF~~ | **DELETED** — same. |
| Airbus | AIR.PA | verified | Commercial aerospace + defense mix | **KEPT** — verified, stays as-is. |
| ~~**Maximus**~~ | ~~MMS~~ | ~~pending~~ | ~~Government IT outsourcing~~ | **FIXED** — moved to cat 19. |

### Cat 16 status
All pending items resolved. Verified companies stay. ETFs deleted. Prompt COMMERCIAL_COMPANY_RULE updated with explicit ETF exclusion and named examples.

---

## Category 17 — Financial Infrastructure & AI Capital

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| **Franklin Templeton** | BEN | Excel | Traditional asset manager — manages mutual funds, not AI fintech | From Excel — "Asset Management / Quantum Investment" subcategory; Franklin is a conventional fund manager |
| **Goldman Sachs** | GS | Excel | Investment bank — AI is used internally, not sold as a product | From Excel — "Project Finance / AI CapEx" is a strategic role, not an AI fintech product |
| **Mitsubishi UFJ Financial** | MUFG | Excel | Japanese mega-bank — traditional banking | From Excel — "Banking / Quantum Finance" subcategory; MUFG is a general bank |
| **Al Rajhi Bank** | 1120.SR | Excel | Saudi Islamic bank — traditional banking | From Excel — "Applied AI / Banking" caught all large banks that mention AI deployment |
| **Bank Central Asia** | BBCA.JK | Excel | Indonesian retail bank | From Excel — same pattern |
| **DBS Group** | D05.SI | Excel | Singaporean bank — AI is an internal deployment, not a commercial product | From Excel — same pattern |
| **Emirates NBD** | EMIRATESNBD.DU | Excel | UAE bank | From Excel — same pattern |
| **HDFC Bank** | HDFCBANK.NS | Excel | Indian retail bank | From Excel — same pattern |
| **ICICI Bank** | ICICIBANK.NS | Excel | Indian retail bank | From Excel — same pattern |
| Coinbase, Betterment, Wealthfront | pending | Crypto exchange / robo-advisory | **KEPT** — use AI meaningfully in financial operations; fit cat 17 under updated rule. |
| ~~**Global X Defense ETF**~~ | ~~SHLD~~ | ~~pending~~ | ~~ETF~~ | **DELETED** — already deleted in cat 16 pass. |
| ~~**Invesco A&D ETF**~~ | ~~PPA~~ | ~~pending~~ | ~~ETF~~ | **DELETED** — same. |
| ~~**iShares US A&D ETF**~~ | ~~ITA~~ | ~~pending~~ | ~~ETF~~ | **DELETED** — same. |
| ~~**SPDR S&P A&D ETF**~~ | ~~XAR~~ | ~~pending~~ | ~~ETF~~ | **DELETED** — same. |

### Cat 17 status
All pending items resolved. Verified banks/asset managers stay under updated "uses AI meaningfully" rule. ETFs deleted. Prompt updated for both cat 17 definition and cheatsheet.

---

## Category 18 — Water & Resource Infrastructure

All 6 companies (Climeon, Ecolab, Itron, Lindsay, Ormat, Veolia) are legitimate Excel seed companies. No obvious misclassifications — this is the cleanest category in the universe.

### Core question for cat 18
> **Cat 18 is clean.** The small size (6 companies) and clear scope kept this category precise. The question going forward is whether there are missing companies worth adding.

---

## Category 19 — Applications & Digital Economy

| Company | Ticker | Status | Issue | Prompt rule that caused it |
|---------|--------|--------|-------|---------------------------|
| **Dentsu Group / Dentsu Group (ADR)** | 4324.T / DNTUY | Excel | Two entries for same company — Japanese advertising agency | From Excel — duplicate; ADR + parent both seeded |
| **Tencent Holdings** | 0700 | pending | Appears here AND in cat 09 (Tencent Cloud) — duplicate across categories | Discovery created a second Tencent entry — **verified Tencent (TCEHY) stays in cat 19; check if 0700 row still exists** |
| **Boeing** | BA | Excel | Aerospace / defense manufacturer — not a digital economy application | From Excel — "AI Beneficiary / End Applications" is too broad; Boeing is primarily cat 16 Defense |
| **Lockheed Martin** | LMT | Excel | Defense contractor | From Excel — same; cat 16 |
| **Northrop Grumman** | NOC | Excel | Defense contractor | From Excel — same; cat 16 |
| **RTX Corp** | RTX | Excel | Defense/aerospace (formerly Raytheon/UTC) | From Excel — same; cat 16 |
| **General Dynamics** | GD | Excel | Defense contractor | From Excel — same; cat 16 |
| **L3Harris** | LHX | Excel | Defense electronics | From Excel — same; cat 16 |
| **Huntington Ingalls** | HII | Excel | Naval shipbuilding — US defense prime | From Excel — same; cat 16 |
| **Elbit Systems** | ESLT | Excel | Israeli defense electronics | From Excel — same; cat 16 |
| **Rheinmetall** | RNMBY | Excel | German defense/armaments — already in cat 05 and flagged; here as ADR | From Excel — duplicate entry across categories |
| **Booz Allen Hamilton** | BAH | Excel | Defense IT / government consulting | From Excel — primarily a defense consulting firm; cat 16 |
| **Leidos** | LDOS | Excel | Defense IT / national security services | From Excel — cat 16 |
| **SAIC** | SAIC | Excel | Defense IT | From Excel — cat 16 |
| **Parsons** | PSN | Excel | Defense infrastructure / technology | From Excel — cat 16 |
| **Mercury Systems** | MRCY | Excel | Defense electronics | From Excel — cat 16 |
| **General Electric** | GE | Excel | Industrial conglomerate — aerospace engines and power generation | From Excel — GE is cat 05 (jet engines) or cat 02 (power); "AI Beneficiary" is too vague |
| **Caterpillar** | CAT | Excel | Heavy equipment / construction machinery | From Excel — "AI Beneficiary" catch-all; Caterpillar is industrial equipment, cat 05 or standalone |
| **Schlumberger** | SLB | Excel | Oilfield services | From Excel — "AI Beneficiary" catch-all; SLB is an energy services company, cat 01 or cat 02 adjacent |
| **JPMorgan Chase** | JPM | Excel | Investment bank | From Excel — "AI Beneficiary" catch-all; giant bank using AI ≠ AI applications company; cat 17 |
| **Visa** | V | Excel | Payment network | From Excel — payments network, cat 17 Financial Infrastructure |
| **Mastercard** | MA | Excel | Payment network | From Excel — same as Visa |
| **BlackRock** | BLK | Excel | Asset manager — investment fund | From Excel — "AI Beneficiary"; BlackRock is an asset manager, excluded as investment fund |
| **Charles Schwab** | SCHW | Excel | Brokerage / wealth management | From Excel — "AI Beneficiary"; cat 17 |
| **CME Group** | CME | Excel | Futures/derivatives exchange operator | From Excel — cat 17 Financial Infrastructure |
| **Intercontinental Exchange** | ICE | Excel | Stock exchange + data | From Excel — cat 17 Financial Infrastructure |
| **S&P Global** | SPGI | Excel | Financial data / ratings | From Excel — cat 17 Financial Infrastructure |
| **Morgan Stanley** | MS | Excel | Investment bank | From Excel — cat 17 |
| **Danaher** | DHR | Excel | Life science instruments conglomerate | From Excel — "AI Beneficiary" catch-all; Danaher makes lab instruments, cat 15 |
| **Thermo Fisher** | TMO | Excel | Life science instruments | From Excel — same as Danaher; cat 15 |
| **10x Genomics** | TXG | Excel | Genomics tools | From Excel — genomics instruments belong in cat 15 |
| **Illumina** | ILMN | Excel | DNA sequencing systems | From Excel — same; cat 15 or cat 04 semiconductor tools |
| **Exscientia** | EXAI | Excel | AI drug discovery company | From Excel — this belongs in cat 15, not cat 19 |
| **Recursion Pharmaceuticals** | RXRX | Excel | AI drug discovery | From Excel — cat 15 |
| **MediaTek** | 2454.TW | Excel | Chip designer — SoCs for mobile and edge | From Excel — "AI SoCs / Edge Compute" subcategory; MediaTek is a semiconductor company, cat 04 |
| **Ambarella** | AMBA | Excel | AI SoC chip designer | From Excel — chip company, cat 04 |
| **Mobileye** | MBLY | Excel | Automotive AI chip + perception software | From Excel — could be cat 04 or cat 13; not an "application" |
| **TDK** | 6762.T | Excel | Electronics components — sensors, batteries, magnetics | From Excel — components maker, cat 04 or cat 05 |
| **Lilium** | LILM | Excel | German eVTOL startup — went bankrupt in 2023 | COMMERCIAL_COMPANY_RULE excludes bankrupt companies; exclusion failed |
| **Faraday Future** | FFAI | Excel | EV startup — essentially defunct / delisted | Same — bankrupt/delisted company slipped through |

### Core question for cat 19
> **"Cat 19 was used as the catch-all bucket for any company that 'benefits from AI' — the 'AI Beneficiary / End Applications' subcategory is the root cause of most misclassifications."**
> Four major bleed patterns from the original Excel:
> 1. **Defense companies** (Boeing, Lockheed, Northrop, RTX, GD, L3Harris, Huntington Ingalls, Elbit, Leidos, SAIC, BAH, Parsons, Mercury) belong in cat 16 — "AI beneficiary" was applied to any company whose products might use AI software.
> 2. **Financial companies** (JPM, Visa, Mastercard, BlackRock, Schwab, CME, ICE, S&P Global, Morgan Stanley) belong in cat 17 — applying the "AI beneficiary" label to giant banks and exchanges bloated cat 19.
> 3. **Life sciences / instruments** (Danaher, Thermo Fisher, 10x Genomics, Illumina, Exscientia, Recursion) belong in cat 15.
> 4. **Chip/hardware companies** (MediaTek, Ambarella, Mobileye, TDK) belong in cat 04 or cat 05.

---

## Prompt fixes to consider (after all categories reviewed)

| Question | Decision |
|----------|----------|
| Cat 01: exclude potash/fertilizer miners explicitly? | TBD |
| Cat 01: PCB makers should be cat 04 — add to exclusion list? | TBD |
| Cat 01: specialty alloy makers — cat 01 or cat 05/16? | TBD |
