"""US-listed read-through links for the tracked Japanese universe.

A signal is only actionable if it points at something a reader can
trade. The customer lists on JAPAN_TICKER_UNIVERSE name the companies a
tracked firm sells to, but several of those (Samsung Electronics, SK
Hynix, SMIC, Denso, MediaTek) are not US-listed, and the same list
repeats on every signal from that company regardless of what happened.
This table answers a different question: when this company moves, which
US-listed names move with it, and how soon.

DRAFTED, NOT VERIFIED. Every link below is drafted from publicly
understood industry structure and needs sign-off before it reaches a
trader-facing page. No link is sourced to a filing or an
investor-relations disclosure.

Each link carries four fields:

``ticker``
    The US-listed symbol. This is the point of the table - a link
    without one cannot be acted on and is not recorded here.

``relationship``
    The consuming frontend's vocabulary, not this module's:
    Customer | Supplier | Competitor | Shared demand. "Shared demand"
    covers two companies that move together because they sell into the
    same end market without trading with each other, which is the
    common case for an equipment maker and its listed peers - calling
    those "Competitor" would overstate a rivalry that may not drive the
    price, and "Customer" would be plainly wrong.

``strength``
    strong | medium | weak. How reliably the Japanese company's result
    tells you something about this name. A peer selling the same
    equipment into the same capex cycle is strong; a diversified
    conglomerate sharing one end market is weak.

``lag``
    same quarter | 1-2 quarters | 2-4 quarters. How long before the
    read-through should show up in the linked company's own numbers.
    Equipment peers report against the same capex cycle, so they move
    together; a materials supplier feeding a fab under construction
    lags by several quarters.
"""
from __future__ import annotations

from typing import Any

# Display names for the US-listed tickers used below, so a consumer
# never has to resolve a symbol itself.
US_NAMES: dict[str, str] = {
    "TER": "Teradyne",
    "ONTO": "Onto Innovation",
    "CAMT": "Camtek",
    "KLAC": "KLA",
    "AMAT": "Applied Materials",
    "LRCX": "Lam Research",
    "ASML": "ASML",
    "NVDA": "Nvidia",
    "AMD": "AMD",
    "INTC": "Intel",
    "TSM": "TSMC",
    "MU": "Micron Technology",
    "TXN": "Texas Instruments",
    "COHR": "Coherent",
    "LITE": "Lumentum",
    "APH": "Amphenol",
    "AAPL": "Apple",
    "GLW": "Corning",
    "ENTG": "Entegris",
    "MKSI": "MKS Instruments",
    "CCMP": "CMC Materials",
    "DD": "DuPont",
    "WDC": "Western Digital",
    "STX": "Seagate",
    "SNPS": "Synopsys",
    "CDNS": "Cadence",
    "MCHP": "Microchip Technology",
    "NXPI": "NXP Semiconductors",
    "ADI": "Analog Devices",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet",
    "ARM": "Arm Holdings",
    "QCOM": "Qualcomm",
    "AVGO": "Broadcom",
}


def _link(ticker: str, relationship: str, strength: str, lag: str,
          connection: str) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "name": US_NAMES[ticker],
        "relationship": relationship,
        "strength": strength,
        "lag": lag,
        "connection": connection,
    }


# code -> links, strongest read first. The frontend shows the first
# three or four as clickable chips, so ordering is meaningful.
JAPAN_READ_THROUGH: dict[str, list[dict[str, Any]]] = {
    # Semiconductor test equipment. Teradyne is the direct listed peer:
    # the two split the ATE market between them.
    "6857": [  # Advantest
        _link("TER", "Competitor", "strong", "same quarter",
              "The other half of the semiconductor test equipment duopoly"),
        _link("ONTO", "Shared demand", "strong", "same quarter",
              "Process control and inspection, same advanced-packaging cycle"),
        _link("CAMT", "Shared demand", "medium", "same quarter",
              "Inspection for advanced packaging, same end demand"),
        _link("NVDA", "Customer", "medium", "1-2 quarters",
              "AI accelerator test demand drives Advantest's order book"),
    ],
    # Broad front-end equipment: the listed US peers sell into the same
    # fab capex budgets.
    "8035": [  # Tokyo Electron
        _link("AMAT", "Competitor", "strong", "same quarter",
              "Competes across deposition and etch, same fab capex cycle"),
        _link("LRCX", "Competitor", "strong", "same quarter",
              "Direct overlap in etch and deposition"),
        _link("KLAC", "Shared demand", "strong", "same quarter",
              "Process control sold into the same fab budgets"),
        _link("ASML", "Shared demand", "medium", "1-2 quarters",
              "Lithography paired with TEL's track systems"),
    ],
    # Dicing and grinding, concentrated in advanced packaging.
    "6146": [  # Disco
        _link("ONTO", "Shared demand", "strong", "same quarter",
              "Advanced packaging equipment, same HBM and chiplet demand"),
        _link("CAMT", "Shared demand", "strong", "same quarter",
              "Packaging inspection against the same back-end cycle"),
        _link("AMAT", "Shared demand", "medium", "1-2 quarters",
              "Overlapping packaging equipment exposure"),
        _link("TSM", "Customer", "medium", "1-2 quarters",
              "Advanced packaging capacity drives dicing tool orders"),
    ],
    # Mask and wafer inspection, effectively unchallenged in EUV mask
    # inspection.
    "6920": [  # Lasertec
        _link("KLAC", "Competitor", "strong", "same quarter",
              "The main listed alternative in inspection and metrology"),
        _link("ASML", "Shared demand", "strong", "1-2 quarters",
              "EUV adoption drives mask inspection demand"),
        _link("ONTO", "Shared demand", "medium", "same quarter",
              "Process control sold into the same leading-edge nodes"),
    ],
    # Fine-diameter optical cable for AI datacentre build-out.
    "5803": [  # Fujikura
        _link("COHR", "Shared demand", "strong", "same quarter",
              "Optical interconnect for the same datacentre build-out"),
        _link("LITE", "Shared demand", "strong", "same quarter",
              "Datacentre optical components, same AI capex driver"),
        _link("APH", "Shared demand", "medium", "1-2 quarters",
              "Interconnect and cabling into the same end market"),
        _link("GLW", "Competitor", "medium", "1-2 quarters",
              "Competing optical fibre supply"),
    ],
    # Silicon wafers and photoresist: upstream of every fab.
    "4063": [  # Shin-Etsu Chemical
        _link("ENTG", "Shared demand", "strong", "1-2 quarters",
              "Materials consumed per wafer start, same utilisation cycle"),
        _link("MKSI", "Shared demand", "medium", "1-2 quarters",
              "Process materials and subsystems into the same fabs"),
        _link("DD", "Competitor", "medium", "2-4 quarters",
              "Overlapping electronic materials"),
        _link("TSM", "Customer", "medium", "2-4 quarters",
              "Wafer demand follows foundry utilisation"),
    ],
    "3436": [  # SUMCO
        _link("ENTG", "Shared demand", "strong", "1-2 quarters",
              "Wafer-start-driven materials demand"),
        _link("MU", "Customer", "strong", "1-2 quarters",
              "Memory wafer demand tracks DRAM and NAND output"),
        _link("TSM", "Customer", "medium", "2-4 quarters",
              "Foundry wafer consumption"),
    ],
    # IC packaging substrates, concentrated in high-end CPU and GPU.
    "4062": [  # Ibiden
        _link("INTC", "Customer", "strong", "1-2 quarters",
              "Substrate supply tied to Intel's CPU output"),
        _link("NVDA", "Customer", "strong", "1-2 quarters",
              "ABF substrate for AI accelerator packaging"),
        _link("AMD", "Customer", "medium", "1-2 quarters",
              "Server CPU and accelerator substrate"),
        _link("AMAT", "Shared demand", "weak", "2-4 quarters",
              "Advanced packaging capacity build-out"),
    ],
    "6967": [  # Shinko Electric
        _link("INTC", "Customer", "strong", "1-2 quarters",
              "Packaging substrate supply to Intel"),
        _link("AMD", "Customer", "medium", "1-2 quarters",
              "Substrate for server and client processors"),
        _link("NVDA", "Customer", "medium", "1-2 quarters",
              "Accelerator packaging substrate"),
    ],
    # Wafer cleaning and surface preparation.
    "7735": [  # Screen Holdings
        _link("LRCX", "Competitor", "strong", "same quarter",
              "Overlapping wafer clean and surface preparation"),
        _link("AMAT", "Competitor", "medium", "same quarter",
              "Competing process equipment into the same fab budgets"),
        _link("TSM", "Customer", "medium", "1-2 quarters",
              "Cleaning tool orders follow foundry capacity"),
    ],
    # Batch deposition, heavily memory-weighted.
    "6525": [  # Kokusai Electric
        _link("AMAT", "Competitor", "strong", "same quarter",
              "Competing deposition equipment"),
        _link("LRCX", "Competitor", "strong", "same quarter",
              "Overlapping deposition into memory fabs"),
        _link("MU", "Customer", "strong", "1-2 quarters",
              "Memory capex drives batch deposition orders"),
    ],
    # Photoresist, where the read-through is to lithography intensity.
    "4186": [  # Tokyo Ohka Kogyo
        _link("ENTG", "Shared demand", "strong", "1-2 quarters",
              "Process chemicals consumed per wafer start"),
        _link("ASML", "Shared demand", "medium", "2-4 quarters",
              "EUV resist demand follows lithography adoption"),
        _link("DD", "Competitor", "medium", "2-4 quarters",
              "Competing semiconductor materials"),
    ],
    "4004": [  # Resonac Holdings
        _link("ENTG", "Shared demand", "strong", "1-2 quarters",
              "Packaging and process materials, same utilisation cycle"),
        _link("WDC", "Customer", "medium", "1-2 quarters",
              "Hard disk media supply"),
        _link("STX", "Customer", "medium", "1-2 quarters",
              "Hard disk media demand tracks nearline drive shipments"),
        _link("DD", "Competitor", "weak", "2-4 quarters",
              "Overlapping electronic materials"),
    ],
    # Moulding and cutting for packaging.
    "6315": [  # Towa
        _link("ONTO", "Shared demand", "strong", "same quarter",
              "Advanced packaging equipment, same back-end cycle"),
        _link("CAMT", "Shared demand", "medium", "same quarter",
              "Packaging process equipment"),
        _link("AMAT", "Shared demand", "weak", "1-2 quarters",
              "Packaging capacity investment"),
    ],
    # Passive components: the read is to handset and auto volume.
    "6981": [  # Murata Manufacturing
        _link("AAPL", "Customer", "strong", "1-2 quarters",
              "MLCC content per iPhone drives order volume"),
        _link("APH", "Shared demand", "medium", "1-2 quarters",
              "Component demand across the same device cycle"),
        _link("QCOM", "Shared demand", "medium", "1-2 quarters",
              "Handset RF content moves with the same build plans"),
    ],
    "6762": [  # TDK
        _link("AAPL", "Customer", "strong", "1-2 quarters",
              "Battery and component supply tied to iPhone volume"),
        _link("APH", "Shared demand", "medium", "1-2 quarters",
              "Shared device-component demand"),
        _link("QCOM", "Shared demand", "weak", "1-2 quarters",
              "Handset content cycle"),
    ],
    # NAND: a direct listed read-across on pricing.
    "285A": [  # Kioxia
        _link("MU", "Competitor", "strong", "same quarter",
              "NAND pricing and supply move together"),
        _link("WDC", "Competitor", "strong", "same quarter",
              "Joint-venture NAND output and shared pricing"),
        _link("STX", "Shared demand", "medium", "1-2 quarters",
              "Storage demand across the same datacentre buyers"),
        _link("AAPL", "Customer", "weak", "1-2 quarters",
              "NAND content in devices"),
    ],
    # Automotive and industrial MCUs.
    "6723": [  # Renesas Electronics
        _link("NXPI", "Competitor", "strong", "same quarter",
              "Automotive MCU and analog, same inventory cycle"),
        _link("MCHP", "Competitor", "strong", "same quarter",
              "MCU demand and channel inventory move together"),
        _link("ADI", "Shared demand", "medium", "1-2 quarters",
              "Industrial and automotive analog demand"),
        _link("TXN", "Competitor", "medium", "1-2 quarters",
              "Overlapping analog and embedded exposure"),
    ],
    # A conglomerate: the semiconductor read-through is weak and
    # indirect, which the strengths below say plainly.
    "6501": [  # Hitachi
        _link("MSFT", "Customer", "weak", "2-4 quarters",
              "Digital systems and cloud partnership"),
        _link("AMZN", "Customer", "weak", "2-4 quarters",
              "Infrastructure and cloud services"),
        _link("AMAT", "Shared demand", "weak", "2-4 quarters",
              "Semiconductor equipment arm, a minority of group revenue"),
    ],
    # A holding company: the read is to its holdings, not its operations.
    "9984": [  # SoftBank Group
        _link("ARM", "Supplier", "strong", "same quarter",
              "Majority-owned; Arm's results flow into group value"),
        _link("NVDA", "Shared demand", "medium", "1-2 quarters",
              "AI infrastructure exposure across the portfolio"),
        _link("AVGO", "Shared demand", "weak", "1-2 quarters",
              "Shared AI silicon demand"),
    ],
}


def links_for(code: str | None) -> list[dict[str, Any]]:
    """Read-through links for one tracked company, strongest first.

    Returns an empty list for an untracked code and for the industry
    reading, which belongs to no single company.
    """
    if not code:
        return []
    return JAPAN_READ_THROUGH.get(code, [])
