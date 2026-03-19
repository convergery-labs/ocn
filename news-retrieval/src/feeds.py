"""RSS feed collections for each news agent domain."""

AI_NEWS_FEEDS = [
    # General AI coverage
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.wired.com/feed/tag/ai/latest/rss",
    "https://www.technologyreview.com/feed/",
    # Compute – hardware, chips, data-centre infrastructure
    "https://www.nextplatform.com/feed/",
    "https://semiengineering.com/feed/",
    "https://www.servethehome.com/feed/",
    # Energy – power, cooling, sustainability
    "https://www.datacenterdynamics.com/en/rss/",
    # Economics – funding, acquisitions, market trends
    "https://news.crunchbase.com/feed/",
    "https://siliconangle.com/feed/",
    # Research – models, papers, benchmarks
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    # Robotics & Physical AI
    "https://spectrum.ieee.org/feeds/feed.rss",
    "https://www.therobotreport.com/feed/",
]

# Feeds that publish infrequently (weekly or less) and return zero articles on
# short day windows. Only polled when days_back >= 7.
AI_NEWS_FEEDS_WEEKLY = [
    # General AI coverage
    "https://huggingface.co/blog/feed.xml",
    # Energy – power, cooling, sustainability
    "https://www.canarymedia.com/rss.xml",
    # Edge & Local AI – on-device inference, maker hardware
    "https://www.hackster.io/feed",
    # AI in Science – research breakthroughs, math
    "https://www.quantamagazine.org/feed/",
    # Policy – regulation, governance, ethics
    "https://www.lawfaremedia.org/feed",
    "https://www.eff.org/rss/updates.xml",
]

# Removed feeds:
#   https://feeds.nature.com/nature/rss/current   – publishes full weekly issue
#       regardless of subject; 75 articles/run with ~0% AI taxonomy relevance
#   https://www.tomshardware.com/feeds/all         – too broad; mostly gaming
#       benchmarks and consumer PC deals unrelated to AI

SMART_MONEY_FEEDS = [
    # Payments & fintech – agentic commerce, payment rails
    "https://www.pymnts.com/feed/",
    "https://www.finextra.com/rss/rss.aspx",
    "https://techcrunch.com/category/fintech/feed/",
    # Crypto & web3 – micropayments, x402, stablecoins for agents
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://www.theblock.co/rss.xml",
    "https://decrypt.co/feed",
    # VC & strategy – monetization models, agent economy analysis
    "https://a16z.com/feed/",
]
