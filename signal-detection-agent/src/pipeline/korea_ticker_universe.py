"""KOREA_TICKER_UNIVERSE - the 20-company tracked universe for
korea_market_signal classification (Korea Signals spec Section 3).

Duplicated from news-retrieval's src/seed.py rather than imported or
fetched live - same pattern as korea_signal_classifier.py's own
_KOREA_TRUSTED_PUBLICATIONS (a copy of news-retrieval's
_KOREA_PRESS_ALLOWLIST) and Taiwan's clause-code table: each service owns
its own copy of a small, rarely-changing lookup table rather than adding a
cross-service dependency for it. Taiwan's classifier doesn't need an
equivalent of its own ticker universe here because Taiwan tickers need no
exclude_terms/group-prefix disambiguation (see news-retrieval's own
TAIWAN_TICKER_UNIVERSE comment) and news-retrieval already sets
metadata.translated_company_name directly - Korea's S7 (qualification
news) genuinely needs the full entry (korean_name + company + exclude_terms
together) to run Filter 2 correctly, since RSS/GDELT articles carry no
ticker metadata of their own at the point this module first sees them.

Kept in sync manually with news-retrieval/src/seed.py's KOREA_TICKER_UNIVERSE
if that list ever changes (add/remove a tracked company, correct a name).
"""
from typing import Any

KOREA_TICKER_UNIVERSE: list[dict[str, Any]] = [
    # Tier 1
    {"ticker": "000660", "company": "SK Hynix", "korean_name": "SK하이닉스", "group_prefix": "SK", "exclude_terms": []},
    {"ticker": "005930", "company": "Samsung Electronics", "korean_name": "삼성전자", "group_prefix": "Samsung", "exclude_terms": ["Samsung C&T", "Samsung Life", "Samsung SDI", "Samsung Fire"]},
    # Tier 2 - memory stacking chain
    {"ticker": "042700", "company": "Hanmi Semiconductor", "korean_name": "한미반도체", "group_prefix": "Hanmi", "exclude_terms": []},
    # Hanwha Semitech (한화세미텍) has no public ticker - see news-retrieval
    # seed.py's own comment for the verification behind this.
    {"ticker": None, "company": "Hanwha Semitech", "korean_name": "한화세미텍", "group_prefix": "Hanwha", "exclude_terms": ["Hanwha Solutions", "Hanwha Aerospace", "Hanwha Life", "Hanwha Ocean", "Hanwha System"], "unlisted": True},
    {"ticker": "089030", "company": "Techwing", "korean_name": "테크윙", "group_prefix": "Techwing", "exclude_terms": []},
    {"ticker": "058470", "company": "Leeno Industrial", "korean_name": "리노공업", "group_prefix": "Leeno", "exclude_terms": []},
    {"ticker": "067310", "company": "Hana Micron", "korean_name": "하나마이크론", "group_prefix": "Hana", "exclude_terms": ["Hana Financial", "Hana Bank", "Hana Tour"]},
    {"ticker": "222800", "company": "Simmtech", "korean_name": "심텍", "group_prefix": "Simmtech", "exclude_terms": []},
    {"ticker": "007660", "company": "Isu Petasys", "korean_name": "이수페타시스", "group_prefix": "Isu", "exclude_terms": []},
    {"ticker": "353200", "company": "Daeduck Electronics", "korean_name": "대덕전자", "group_prefix": "Daeduck", "exclude_terms": ["Daeduck GDS"]},
    # Tier 3 - equipment, materials, chip making and power
    {"ticker": "402340", "company": "SK Square", "korean_name": "SK스퀘어", "group_prefix": "SK", "exclude_terms": []},
    {"ticker": "000990", "company": "DB HiTek", "korean_name": "DB하이텍", "group_prefix": "DB", "exclude_terms": ["DB Insurance", "DB Financial"]},
    {"ticker": "009150", "company": "Samsung Electro-Mechanics", "korean_name": "삼성전기", "group_prefix": "Samsung", "exclude_terms": ["Samsung C&T", "Samsung Life", "Samsung SDI", "Samsung Fire"]},
    {"ticker": "011070", "company": "LG Innotek", "korean_name": "LG이노텍", "group_prefix": "LG", "exclude_terms": ["LG Electronics", "LG Chem", "LG Display", "LG Energy Solution", "LG Uplus"]},
    {"ticker": "036930", "company": "Jusung Engineering", "korean_name": "주성엔지니어링", "group_prefix": "Jusung", "exclude_terms": []},
    {"ticker": "240810", "company": "Wonik IPS", "korean_name": "원익IPS", "group_prefix": "Wonik", "exclude_terms": ["Wonik Materials", "Wonik Holdings"]},
    {"ticker": "319660", "company": "PSK", "korean_name": "피에스케이", "group_prefix": "PSK", "exclude_terms": []},
    {"ticker": "357780", "company": "Soulbrain", "korean_name": "솔브레인", "group_prefix": "Soulbrain", "exclude_terms": []},
    {"ticker": "267260", "company": "HD Hyundai Electric", "korean_name": "HD현대일렉트릭", "group_prefix": "HD Hyundai", "exclude_terms": ["HD Hyundai Heavy Industries", "HD Hyundai Marine"]},
    {"ticker": "010120", "company": "LS Electric", "korean_name": "LS일렉트릭", "group_prefix": "LS", "exclude_terms": ["LS Cable", "LS Materials"]},
]
