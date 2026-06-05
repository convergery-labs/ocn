"""Seed the database with initial domain and source data.

Run directly to populate a fresh database:

    python seed.py

The script is idempotent - rows that already exist (matched by slug
or URL) are silently skipped.
"""
import json
import logging
from typing import Any

from db import get_db, init_db, transaction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

RUN_STATUSES: list[str] = ["running", "completed", "failed"]

FREQUENCIES: list[dict[str, Any]] = [
    {"name": "daily",   "min_days_back": 1},
    {"name": "weekly",  "min_days_back": 7},
    {"name": "monthly", "min_days_back": 30},
]

DOMAINS: list[dict[str, Any]] = [
    {
        "name": "AI News",
        "slug": "ai_news",
        "description": (
            "Covers AI models, hardware, semiconductors, data centre"
            " infrastructure, energy, robotics, enterprise AI,"
            " security, policy, funding, and applied science."
        ),
    },
    {
        "name": "Smart Money",
        "slug": "smart_money",
        "description": (
            "Covers agentic payments, stablecoins, digital assets,"
            " embedded finance, cross-border settlement, AI fraud"
            " detection, and enterprise treasury automation."
        ),
    },
]


NEWSAPI_SOURCES: list[dict[str, Any]] = [
    {
        "domain_slug": "ai_news",
        "url": "newsapi:top-headlines",
        "name": "NewsAPI",
        "source_type": "newsapi",
        "frequency_name": "daily",
        "description": "Top headlines from technology, science, and business categories.",
        "config": {
            "endpoint": "top-headlines",
            "categories": ["technology", "science", "business"],
            "language": "en",
        },
    },
]

GOOGLE_NEWS_SOURCE: dict[str, Any] = {
    "domain_slug": "ai_news",
    "url": "google_news",
    "name": "Google News",
    "source_type": "google_news",
    "frequency_name": "daily",
    "description": "Google News search across AI topics via SerpAPI.",
    "config": {
        "queries": [
            "artificial intelligence",
            "generative AI LLM",
            "machine learning deep learning",
            "AI chips GPU semiconductors",
            "AI regulation policy",
            "foundation models AI startups",
            "AI data training datasets",
        ],
    },
}

SUBSTACK_SOURCES: list[dict[str, Any]] = [
    {
        "domain_slug": "ai_news",
        "url": "https://importai.substack.com/feed",
        "name": "Import AI",
        "frequency_name": "weekly",
        "description": "Weekly analysis of cutting-edge AI research.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://simonw.substack.com/feed",
        "name": "Simon Willison's Newsletter",
        "frequency_name": "weekly",
        "description": "Hands-on AI/devtools/open-source analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://decision.substack.com/feed",
        "name": "Decision Intelligence",
        "frequency_name": "weekly",
        "description": "Cassie Kozyrkov on AI, decision science, and management.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://artificialintelligencemadesimple.substack.com/feed",
        "name": "Artificial Intelligence Made Simple",
        "frequency_name": "weekly",
        "description": "Technical, social and economic angles on AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://berkeleyrdi.substack.com/feed",
        "name": "Agentic AI Weekly",
        "frequency_name": "weekly",
        "description": "AI agents and research updates.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://artificialintelligenceact.substack.com/feed",
        "name": "EU AI Act Newsletter",
        "frequency_name": "weekly",
        "description": "EU AI Act and regulation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiguide.substack.com/feed",
        "name": "AI: A Guide for Thinking Humans",
        "frequency_name": "weekly",
        "description": "Melanie Mitchell on AI for thoughtful readers.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiagentssimplified.substack.com/feed",
        "name": "AI Agents Simplified",
        "frequency_name": "weekly",
        "description": "Practical explainers on AI agents.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://diamantai.substack.com/feed",
        "name": "DiamantAI",
        "frequency_name": "weekly",
        "description": "Agentic AI and engineering resources.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://wrk3.substack.com/feed",
        "name": "Work3 - The Future of Work",
        "frequency_name": "weekly",
        "description": "AI and work transformation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thezvi.substack.com/feed",
        "name": "Don't Worry About the Vase",
        "frequency_name": "weekly",
        "description": "Zvi on AI discourse and developments.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://addyo.substack.com/feed",
        "name": "Elevate",
        "frequency_name": "weekly",
        "description": "Addy Osmani on AI and software development.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://jamwithai.substack.com/feed",
        "name": "Jam with AI",
        "frequency_name": "weekly",
        "description": "AI tools and workflows.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://substack.jurgenappelo.com/feed",
        "name": "The Maverick Mapmaker",
        "frequency_name": "weekly",
        "description": "AI and management/future of work.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://cosmosinstitute.substack.com/feed",
        "name": "Cosmos Institute",
        "frequency_name": "weekly",
        "description": "AI and ideas.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thenuancedperspective.substack.com/feed",
        "name": "The Nuanced Perspective",
        "frequency_name": "weekly",
        "description": "Nuanced AI analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aixeducation.substack.com/feed",
        "name": "AI x Education",
        "frequency_name": "weekly",
        "description": "AI and education.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://nickpotkalitsky.substack.com/feed",
        "name": "Educating AI",
        "frequency_name": "weekly",
        "description": "Teaching and education with AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://designingwithai.substack.com/feed",
        "name": "Designing with AI",
        "frequency_name": "weekly",
        "description": "Design workflows with AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://epochai.substack.com/feed",
        "name": "Epoch AI",
        "frequency_name": "weekly",
        "description": "Benchmarks, scaling and research data.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theaileadershipedge.substack.com/feed",
        "name": "The AI Leadership Edge",
        "frequency_name": "weekly",
        "description": "Leadership and AI transformation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thedigitalleader.substack.com/feed",
        "name": "The Digital Leader",
        "frequency_name": "weekly",
        "description": "Digital strategy and AI transformation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aifrontiersmedia.substack.com/feed",
        "name": "AI Frontiers",
        "frequency_name": "weekly",
        "description": "Frontier AI coverage.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theagentarchitect.substack.com/feed",
        "name": "The AI Agent Architect",
        "frequency_name": "weekly",
        "description": "Architecting AI agents.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://oliverpatel.substack.com/feed",
        "name": "Enterprise AI Governance",
        "frequency_name": "weekly",
        "description": "Governance in enterprise AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://futureworklife.substack.com/feed",
        "name": "Ollie on Work",
        "frequency_name": "weekly",
        "description": "Work, management, AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aimaker.substack.com/feed",
        "name": "The AI Maker",
        "frequency_name": "weekly",
        "description": "Maker-focused AI building and workflows.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://amistrongeryet.substack.com/feed",
        "name": "Second Thoughts",
        "frequency_name": "weekly",
        "description": "Thoughtful AI and product commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://frontierai.substack.com/feed",
        "name": "The AI Frontier",
        "frequency_name": "weekly",
        "description": "Frontier AI systems and economics.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://themediabrain.substack.com/feed",
        "name": "Peter Csathy's the brAIn",
        "frequency_name": "weekly",
        "description": "AI and media intelligence.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiblewmymind.substack.com/feed",
        "name": "AI blew my mind",
        "frequency_name": "weekly",
        "description": "Accessible AI insights.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://stevenadler.substack.com/feed",
        "name": "Clear-Eyed AI",
        "frequency_name": "weekly",
        "description": "Grounded AI policy and safety commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://msukhareva.substack.com/feed",
        "name": "AI Realist",
        "frequency_name": "weekly",
        "description": "Pragmatic view of AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thestrategystack.substack.com/feed",
        "name": "The Strategy Stack",
        "frequency_name": "weekly",
        "description": "Strategy thinking with AI lens.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theaimonitor.substack.com/feed",
        "name": "The AI Monitor",
        "frequency_name": "weekly",
        "description": "Monitoring AI developments.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiagenteconomy.substack.com/feed",
        "name": "The AI Agent Economy",
        "frequency_name": "weekly",
        "description": "Agent economy and startups.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aicentral.substack.com/feed",
        "name": "AI Central",
        "frequency_name": "weekly",
        "description": "General AI coverage.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://unhypedai.substack.com/feed",
        "name": "Unhyped AI",
        "frequency_name": "weekly",
        "description": "Low-hype AI analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theaiphilosopher.substack.com/feed",
        "name": "The AI Philosopher",
        "frequency_name": "weekly",
        "description": "Philosophical takes on AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thehumanplaybook.substack.com/feed",
        "name": "The Human Playbook",
        "frequency_name": "weekly",
        "description": "Human skills in AI era.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://honestai.substack.com/feed",
        "name": "Honest AI",
        "frequency_name": "weekly",
        "description": "Honest takes on AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://kaystoner.substack.com/feed",
        "name": "What Good Is AI?",
        "frequency_name": "weekly",
        "description": "Critical practical commentary on AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://rafebrena.substack.com/feed",
        "name": "The Skeptic AI Enthusiast",
        "frequency_name": "weekly",
        "description": "Skeptical but interested AI coverage.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://utopiainbeta.substack.com/feed",
        "name": "Utopia in Beta",
        "frequency_name": "weekly",
        "description": "AI and future concepts.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://engineeringharmony.substack.com/feed",
        "name": "Engineering Harmony",
        "frequency_name": "weekly",
        "description": "AI and engineering thinking.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aihumanity.substack.com/feed",
        "name": "AI for Humanity",
        "frequency_name": "weekly",
        "description": "AI for social good and society.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://diamantinoalmeida.substack.com/feed",
        "name": "Leadership as a Verb",
        "frequency_name": "weekly",
        "description": "Leadership and AI transition.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://futurebraining.substack.com/feed",
        "name": "Futurebraining",
        "frequency_name": "weekly",
        "description": "Future-oriented AI commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://haridutt.substack.com/feed",
        "name": "The Turing Pilgrim",
        "frequency_name": "weekly",
        "description": "AI and broader reflection.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thepromptisthenovel.substack.com/feed",
        "name": "The Prompt Is the Novel",
        "frequency_name": "weekly",
        "description": "Prompting and generative writing.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aicloudweekly.substack.com/feed",
        "name": "AI & Cloud Weekly",
        "frequency_name": "weekly",
        "description": "AI and cloud weekly roundup.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aigovernancelead.substack.com/feed",
        "name": "AI Governance Ethics and Leadership",
        "frequency_name": "weekly",
        "description": "Governance and leadership.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://pascalbornet.substack.com/feed",
        "name": "IRREPLACEABLE with AI",
        "frequency_name": "weekly",
        "description": "Human + AI transformation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://solrashidi.substack.com/feed",
        "name": "The Sol of AI",
        "frequency_name": "weekly",
        "description": "Pragmatic AI for technologists and non-technologists.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://ruben.substack.com/feed",
        "name": "How to AI",
        "frequency_name": "weekly",
        "description": "Step-by-step AI workflows.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://mitgenerationai.substack.com/feed",
        "name": "Generation AI",
        "frequency_name": "weekly",
        "description": "MIT Working Group on Generative AI and the future of work.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiedusimplified.substack.com/feed",
        "name": "AI + Education = Simplified",
        "frequency_name": "weekly",
        "description": "AI and education for teachers.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiandhowweteach.substack.com/feed",
        "name": "AI & How We Teach",
        "frequency_name": "weekly",
        "description": "AI-aware teaching and literacy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://wonderingaboutai.substack.com/feed",
        "name": "Wondering About AI",
        "frequency_name": "weekly",
        "description": "Leadership and AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://taoofai.substack.com/feed",
        "name": "Tao of AI",
        "frequency_name": "weekly",
        "description": "AI strategy and philosophy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://nextplayso.substack.com/feed",
        "name": "next play",
        "frequency_name": "weekly",
        "description": "Curated opportunities and deep tech content.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://metatrends.substack.com/feed",
        "name": "Metatrends",
        "frequency_name": "weekly",
        "description": "Future-facing technology trends.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://linas.substack.com/feed",
        "name": "Linas's Newsletter",
        "frequency_name": "weekly",
        "description": "Finance x AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thechipletter.substack.com/feed",
        "name": "The Chip Letter",
        "frequency_name": "weekly",
        "description": (
            "Computer history and architecture with semiconductor"
            " relevance."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://marklapedus.substack.com/feed",
        "name": "Semiecosystem",
        "frequency_name": "weekly",
        "description": "Semiconductor ecosystem commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://metacircuits.substack.com/feed",
        "name": "The Circuit",
        "frequency_name": "weekly",
        "description": "Helping business leaders become better AI operators.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theunchartedalgorithm.substack.com/feed",
        "name": "The Uncharted Algorithm",
        "frequency_name": "weekly",
        "description": "AI, enterprise, culture, future of work.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://interestingengineering.substack.com/feed",
        "name": "Interesting Engineering++",
        "frequency_name": "weekly",
        "description": "Engineering/tech commentary with AI relevance.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://dataintelligenceplatform.substack.com/feed",
        "name": "Data Intelligence Platform",
        "frequency_name": "weekly",
        "description": "Data platform and infrastructure recommendations.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://cloudsecurityguy.substack.com/feed",
        "name": "The Cloud Security Guy",
        "frequency_name": "weekly",
        "description": "Cloud security with AI chip/infrastructure links.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://connectingai.substack.com/feed",
        "name": "ConnectingAI",
        "frequency_name": "weekly",
        "description": "Hardware enables the future of AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://anastasiintech.substack.com/feed",
        "name": "Deep in Tech Newsletter",
        "frequency_name": "weekly",
        "description": "AI data centers, optics, power systems.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://iamfabian.substack.com/feed",
        "name": "Fabian's Substack",
        "frequency_name": "weekly",
        "description": (
            "Product and technology deep dives in optics and AI infra."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://gadallon.substack.com/feed",
        "name": "Gadallon",
        "frequency_name": "weekly",
        "description": "AI infrastructure boom and supply chain.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://axautikgroupllc.substack.com/feed",
        "name": "Patrick Kennedy's Axautik Group",
        "frequency_name": "weekly",
        "description": "Server and hardware analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thefiddler.substack.com/feed",
        "name": "Fiddler on the Proof",
        "frequency_name": "weekly",
        "description": "Science/math with AI adjacency.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theneurotechnewsletter.substack.com/feed",
        "name": "The Neurotech Newsletter",
        "frequency_name": "weekly",
        "description": "Neurotechnology with AI relevance.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://mariannanakos.substack.com/feed",
        "name": "A2S | Automate to Scale",
        "frequency_name": "weekly",
        "description": "Automation and AI integration for scaling.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://harrybloom.substack.com/feed",
        "name": "The Financial Philosopher",
        "frequency_name": "weekly",
        "description": "Financial philosophy with tech lenses.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://khanfk.substack.com/feed",
        "name": "Technicity",
        "frequency_name": "weekly",
        "description": "Technology, business and AI intersections.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://oneusefulthing.substack.com/feed",
        "name": "One Useful Thing",
        "frequency_name": "weekly",
        "description": "Ethan Mollick on practical AI applications and research.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://understandingai.substack.com/feed",
        "name": "Understanding AI",
        "frequency_name": "weekly",
        "description": "Timothy Lee on AI research and policy analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://magazine.sebastianraschka.com/feed",
        "name": "Ahead of AI",
        "frequency_name": "weekly",
        "description": "Sebastian Raschka on ML research and engineering.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://newsletter.safe.ai/feed",
        "name": "AI Safety Newsletter",
        "frequency_name": "weekly",
        "description": "Center for AI Safety - AI alignment and safety research.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theaiopportunities.com/feed",
        "name": "The AI Opportunity",
        "frequency_name": "weekly",
        "description": "AI business opportunities and market analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://brief.montrealethics.ai/feed",
        "name": "The AI Ethics Brief",
        "frequency_name": "weekly",
        "description": "Montreal AI Ethics Institute - AI ethics and governance.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://blog.ai-futures.org/feed",
        "name": "AI Futures Project",
        "frequency_name": "weekly",
        "description": "Long-range AI futures and scenario planning.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://whytryai.com/feed",
        "name": "Why Try AI",
        "frequency_name": "weekly",
        "description": "Practical AI tool introductions and guides.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiadopters.club/feed",
        "name": "AI Adopters Club",
        "frequency_name": "weekly",
        "description": "AI adoption strategies for organisations.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aidisruption.ai/feed",
        "name": "AI Disruption",
        "frequency_name": "weekly",
        "description": "AI strategy and disruption for business leaders.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://workfutures.io/feed",
        "name": "workfutures.io",
        "frequency_name": "weekly",
        "description": "Future of work and AI transformation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://connectedideasproject.com/feed",
        "name": "The Connected Ideas Project",
        "frequency_name": "weekly",
        "description": "Technology and AI ideas synthesis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://2ndorderthinkers.com/feed",
        "name": "2nd Order Thinkers",
        "frequency_name": "weekly",
        "description": "Second-order effects of AI on management and society.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://newsletter.forethought.org/feed",
        "name": "ForeWord",
        "frequency_name": "weekly",
        "description": "Forethought Institute - AI research and policy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://academy.shiftbase.info/feed",
        "name": "Shift*Academy",
        "frequency_name": "weekly",
        "description": "Organisational change and AI leadership.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://phiand.ai/feed",
        "name": "Phi / AI",
        "frequency_name": "weekly",
        "description": "AI philosophy, ideas, and cultural commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://effthealgorithm.com/feed",
        "name": "Eff the Algorithm",
        "frequency_name": "weekly",
        "description": "Critical perspectives on algorithms and AI in society.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://pseudorandombits.io/feed",
        "name": "Pseudorandom Bits",
        "frequency_name": "weekly",
        "description": "AI and computing commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://newsletter.aipolicybulletin.org/feed",
        "name": "AI Policy Bulletin Newsletter",
        "frequency_name": "weekly",
        "description": "AI policy tracking and regulatory updates.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aitidbits.ai/feed",
        "name": "AI Tidbits",
        "frequency_name": "weekly",
        "description": "Curated AI news and tidbits.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://brennanmcdonald.com/feed",
        "name": "Brennan McDonald\'s Newsletter",
        "frequency_name": "weekly",
        "description": "AI and software engineering commentary.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://humanandmachine.com/feed",
        "name": "Human and Machine",
        "frequency_name": "weekly",
        "description": "Humans and AI working together - practical perspectives.",
    },

    {
        "domain_slug": "ai_news",
        "url": "https://readings.ramisayar.com/feed",
        "name": "Rami\'s Readings",
        "frequency_name": "weekly",
        "description": "Curated AI and technology readings.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://writing.antonleicht.me/feed",
        "name": "Threading the Needle",
        "frequency_name": "weekly",
        "description": "AI and engineering.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiweekender.substack.com/feed",
        "name": "AI Weekender",
        "frequency_name": "weekly",
        "description": "Weekly AI news digest.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://tylerfolkman.substack.com/feed",
        "name": "The AI Architect",
        "frequency_name": "weekly",
        "description": "AI architecture and coding tools.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://airabbithole.substack.com/feed",
        "name": "The AI Rabbit Hole",
        "frequency_name": "weekly",
        "description": "Deep dives into AI topics and experiments.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://shmulc.substack.com/feed",
        "name": "AI Superhero",
        "frequency_name": "weekly",
        "description": "AI tools and productivity tips.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://the-ai-corner.com/feed",
        "name": "The AI Corner",
        "frequency_name": "weekly",
        "description": "AI tools, workflows, and use cases.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://creatoreconomy.so/feed",
        "name": "Behind the Craft",
        "frequency_name": "weekly",
        "description": "AI tools for creators and the creator economy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thevccorner.com/feed",
        "name": "The VC Corner",
        "frequency_name": "weekly",
        "description": "Venture capital and AI startup landscape.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://cfooffice.io/feed",
        "name": "AI CFO Office",
        "frequency_name": "weekly",
        "description": "AI in finance and CFO office automation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://newsletter.mkt1.co/feed",
        "name": "MKT1 Newsletter",
        "frequency_name": "weekly",
        "description": "AI in startup marketing and growth.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://sebastianbarros.substack.com/feed",
        "name": "Sebastian Barros Newsletter",
        "frequency_name": "weekly",
        "description": "Cloud, AI, and connectivity trends.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.globaldatacenterhub.com/feed",
        "name": "Global Data Center Hub",
        "frequency_name": "weekly",
        "description": "Data centre infrastructure and AI compute.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://datacenterfervor.substack.com/feed",
        "name": "Data Center Fervor",
        "frequency_name": "weekly",
        "description": "Data centre industry news and analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://dirttodata.substack.com/feed",
        "name": "Dirt to Data",
        "frequency_name": "weekly",
        "description": "Data centre development, land, and power strategy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://sharongoldman.substack.com/feed",
        "name": "AI Side Notes with Sharon Goldman",
        "frequency_name": "weekly",
        "description": "Fortune reporter on AI industry notes and analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://techsoda.substack.com/feed",
        "name": "TechSoda",
        "frequency_name": "weekly",
        "description": "Semiconductors, optical, and AI infrastructure.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.technostatecraft.com/feed",
        "name": "Techno-Statecraft",
        "frequency_name": "weekly",
        "description": "Technology and statecraft - geopolitics of AI and semis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://semifundamental.substack.com/feed",
        "name": "Semi Fundamental",
        "frequency_name": "weekly",
        "description": "AI and semiconductor supply chain fundamentals.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://chipinsights.net/feed",
        "name": "Chip Insights",
        "frequency_name": "weekly",
        "description": "Semiconductor industry insights and analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.22ndcenturyfrontier.com/feed",
        "name": "22nd Century Frontier",
        "frequency_name": "weekly",
        "description": "Frontier technology and deep tech investing.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.augmentedswe.com/feed",
        "name": "The AI-Augmented Engineer",
        "frequency_name": "weekly",
        "description": "AI tools for software engineers.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://businessengineer.ai/feed",
        "name": "The Business Engineer",
        "frequency_name": "weekly",
        "description": "Business strategy and engineering with AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://scsp222.substack.com/feed",
        "name": "Special Competitive Studies Project",
        "frequency_name": "weekly",
        "description": "US technology competitiveness and AI strategy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://tarotcapital.substack.com/feed",
        "name": "Tarot Capital",
        "frequency_name": "weekly",
        "description": "Incentive-driven technology investing.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://arushisharmafrank.substack.com/feed",
        "name": "Teach What I Know",
        "frequency_name": "weekly",
        "description": "Energy markets, grid policy, and AI infrastructure power.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://cozora.substack.com/feed",
        "name": "Cozora",
        "frequency_name": "weekly",
        "description": "AI creator tools and workshops.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thoughtforms.substack.com/feed",
        "name": "Thoughtforms",
        "frequency_name": "weekly",
        "description": "Technology, business, design, and culture futures.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://theslowai.substack.com/feed",
        "name": "Slow AI",
        "frequency_name": "weekly",
        "description": "Critical AI literacy and thoughtful AI engagement.",
    },

    {
        "domain_slug": "ai_news",
        "url": "https://mackcollier.substack.com/feed",
        "name": "Backstage Pass",
        "frequency_name": "weekly",
        "description": "AI in social media and community strategy.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://thehumanco.substack.com/feed",
        "name": "The Human Stack",
        "frequency_name": "weekly",
        "description": "AI, future of work, and HR/L&D leadership.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://fafi25.substack.com/feed",
        "name": "Lights On",
        "frequency_name": "weekly",
        "description": "AI business and productivity.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiinuse.substack.com/feed",
        "name": "Operating",
        "frequency_name": "weekly",
        "description": "AI in operational business contexts.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://3foldoutcomes.substack.com/feed",
        "name": "3Fold Outcomes",
        "frequency_name": "weekly",
        "description": "M&A, organisational design, and AI.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://vickyho.substack.com/feed",
        "name": "VK 科技閱讀時間",
        "frequency_name": "weekly",
        "description": "Chinese-language technology and AI reading curation.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://purposefulai.substack.com/feed",
        "name": "Purposeful AI",
        "frequency_name": "weekly",
        "description": "AI in higher education and nonprofits.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://aiinfrastructure.substack.com/feed",
        "name": "AI Infrastructure Digest",
        "frequency_name": "weekly",
        "description": "AI infrastructure news and analysis.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://inferenceatscale.substack.com/feed",
        "name": "Inference at Scale",
        "frequency_name": "weekly",
        "description": "AI inference infrastructure and deployment.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://llmengineer.substack.com/feed",
        "name": "LLM Engineer Weekly",
        "frequency_name": "weekly",
        "description": "LLM engineering tools and techniques.",
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.promptengineering.org/feed",
        "name": "Prompt Engineering Daily",
        "frequency_name": "weekly",
        "description": "Prompt engineering techniques and research.",
    },
]

SOURCES: list[dict[str, Any]] = [
    # ------------------------------------------------------------------
    # AI News
    # ------------------------------------------------------------------
    {
        "domain_slug": "ai_news",
        "url": "https://venturebeat.com/category/ai/feed/",
        "name": "VentureBeat AI",
        "frequency_name": "daily",
        "description": (
            "The leading source for transformative tech news with"
            " deep AI, machine learning, and data coverage for"
            " business leaders."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": (
            "https://www.theverge.com/rss/ai-artificial-intelligence"
            "/index.xml"
        ),
        "name": "The Verge AI",
        "frequency_name": "daily",
        "description": (
            "Technology news, reviews, and culture covering gadgets,"
            " platforms, AI tools, and how tech shapes everyday life."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": (
            "https://techcrunch.com/category/artificial-intelligence"
            "/feed/"
        ),
        "name": "TechCrunch AI",
        "frequency_name": "daily",
        "description": (
            "AI-focused startup and technology news covering funding,"
            " launches, and innovation from TechCrunch."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.wired.com/feed/tag/ai/latest/rss",
        "name": "Wired AI",
        "frequency_name": "daily",
        "description": (
            "Covers how AI affects culture, economy, and politics,"
            " from model releases to societal implications."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.technologyreview.com/feed/",
        "name": "MIT Technology Review",
        "frequency_name": "daily",
        "description": (
            "Covers emerging technologies and their impact on"
            " society, business, and the future, published by MIT."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.nextplatform.com/feed/",
        "name": "The Next Platform",
        "frequency_name": "daily",
        "description": (
            "In-depth coverage of high-end computing at large"
            " enterprises, supercomputing centres, hyperscale data"
            " centres, and public clouds."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://semiengineering.com/feed/",
        "name": "Semiconductor Engineering",
        "frequency_name": "daily",
        "description": (
            "Deep technical coverage of semiconductor design,"
            " manufacturing, verification, and EDA for chip"
            " engineers."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.servethehome.com/feed/",
        "name": "ServeTheHome",
        "frequency_name": "daily",
        "description": (
            "Covers servers, storage, networking, and high-end"
            " workstation hardware for IT professionals and"
            " enthusiasts."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.datacenterdynamics.com/en/rss/",
        "name": "Data Center Dynamics",
        "frequency_name": "daily",
        "description": (
            "News and analysis on data centre infrastructure,"
            " hyperscale cloud, colocation, AI workloads, and"
            " energy."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://news.crunchbase.com/feed/",
        "name": "Crunchbase News",
        "frequency_name": "daily",
        "description": (
            "Startup funding trends, investment rounds, and private"
            " company intelligence from Crunchbase."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://siliconangle.com/feed/",
        "name": "SiliconAngle",
        "frequency_name": "daily",
        "description": (
            "The trusted voice of enterprise technology, reporting"
            " on AI, cloud, security, and data infrastructure for"
            " IT leaders."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": (
            "https://feeds.arstechnica.com/arstechnica/technology-lab"
        ),
        "name": "Ars Technica",
        "frequency_name": "daily",
        "description": (
            "In-depth technology journalism covering science, policy,"
            " hardware, and software with academic-level rigour."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://spectrum.ieee.org/feeds/feed.rss",
        "name": "IEEE Spectrum",
        "frequency_name": "daily",
        "description": (
            "The flagship publication of IEEE, covering engineering,"
            " electronics, AI, robotics, and emerging technology."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.therobotreport.com/feed/",
        "name": "The Robot Report",
        "frequency_name": "daily",
        "description": (
            "News and analysis on commercial robotics, autonomous"
            " systems, AI for robots, and industrial automation."
        ),
    },
    # Weekly feeds - only polled when days_back >= 7
    {
        "domain_slug": "ai_news",
        "url": "https://huggingface.co/blog/feed.xml",
        "name": "Hugging Face Blog",
        "frequency_name": "weekly",
        "description": (
            "Covers machine learning research, open-source AI tools,"
            " transformers, and practical implementation guides."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.canarymedia.com/rss.xml",
        "name": "Canary Media",
        "frequency_name": "weekly",
        "description": (
            "Nonprofit journalism covering the clean energy"
            " transition, decarbonisation, and climate technology"
            " markets."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.hackster.io/feed",
        "name": "Hackster.io",
        "frequency_name": "weekly",
        "description": (
            "Community platform for hardware developers covering ML,"
            " IoT, robotics, and maker projects with emerging tech."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.quantamagazine.org/feed/",
        "name": "Quanta Magazine",
        "frequency_name": "weekly",
        "description": (
            "Science journalism covering mathematics, theoretical"
            " physics, computer science, and the basic life"
            " sciences."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.lawfaremedia.org/feed",
        "name": "Lawfare",
        "frequency_name": "weekly",
        "description": (
            "Non-partisan analysis of national security law,"
            " cybersecurity, executive powers, content moderation,"
            " and AI governance."
        ),
    },
    {
        "domain_slug": "ai_news",
        "url": "https://www.eff.org/rss/updates.xml",
        "name": "EFF",
        "frequency_name": "weekly",
        "description": (
            "The Electronic Frontier Foundation covers digital civil"
            " liberties, privacy, surveillance, and technology"
            " policy."
        ),
    },
    # ------------------------------------------------------------------
    # Smart Money
    # ------------------------------------------------------------------
    {
        "domain_slug": "smart_money",
        "url": "https://www.pymnts.com/feed/",
        "name": "PYMNTS",
        "frequency_name": "daily",
        "description": (
            "Global data, news, and insights on innovation in"
            " payments and the connected economy."
        ),
    },
    {
        "domain_slug": "smart_money",
        "url": "https://www.finextra.com/rss/rss.aspx",
        "name": "Finextra",
        "frequency_name": "daily",
        "description": (
            "The leading global newswire for financial technology"
            " professionals, covering fintech, payments, banking,"
            " and crypto."
        ),
    },
    {
        "domain_slug": "smart_money",
        "url": "https://techcrunch.com/category/fintech/feed/",
        "name": "TechCrunch Fintech",
        "frequency_name": "daily",
        "description": (
            "Fintech-focused coverage of startups, funding, and"
            " innovation in payments and financial services."
        ),
    },
    {
        "domain_slug": "smart_money",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "name": "CoinDesk",
        "frequency_name": "daily",
        "description": (
            "Leading cryptocurrency and blockchain news, with market"
            " data, policy analysis, and DeFi coverage."
        ),
    },
    {
        "domain_slug": "smart_money",
        "url": "https://www.theblock.co/rss.xml",
        "name": "The Block",
        "frequency_name": "daily",
        "description": (
            "Breaking news, research, and analysis on Bitcoin,"
            " Ethereum, and digital assets for crypto professionals."
        ),
    },
    {
        "domain_slug": "smart_money",
        "url": "https://decrypt.co/feed",
        "name": "Decrypt",
        "frequency_name": "daily",
        "description": (
            "Independent crypto and AI news covering blockchain,"
            " digital assets, culture, and emerging technology."
        ),
    },
    {
        "domain_slug": "smart_money",
        "url": "https://a16z.com/feed/",
        "name": "a16z",
        "frequency_name": "daily",
        "description": (
            "Andreessen Horowitz publishes analysis, research, and"
            " opinion on technology, crypto, AI, and venture"
            " investing."
        ),
    },
    # ------------------------------------------------------------------
    # Substack newsletters (free tier - full body in RSS)
    # ------------------------------------------------------------------
    *SUBSTACK_SOURCES,
    # ------------------------------------------------------------------
    # SerpAPI Google News
    # ------------------------------------------------------------------
    GOOGLE_NEWS_SOURCE,
    # ------------------------------------------------------------------
    # NewsAPI top-headlines
    # ------------------------------------------------------------------
    *NEWSAPI_SOURCES,
]

# ---------------------------------------------------------------------------
# Seeding logic
# ---------------------------------------------------------------------------


def seed() -> None:
    """Insert frequencies, domains, taxonomies, and sources.

    Skips rows that already exist. Safe to call multiple times.
    All inserts run in a single transaction; a failure rolls back
    the entire seed run.
    """
    with transaction():
        # Run statuses (must be seeded before runs table is used)
        with get_db() as conn:
            conn.execute_values(
                "INSERT INTO run_statuses (name)"
                " VALUES %s ON CONFLICT (name) DO NOTHING",
                [(s,) for s in RUN_STATUSES],
            )
        logger.info("Seeded %d run statuses.", len(RUN_STATUSES))

        # Frequencies
        with get_db() as conn:
            conn.execute_values(
                "INSERT INTO frequencies (name, min_days_back)"
                " VALUES %s ON CONFLICT (name) DO NOTHING",
                [(f["name"], f["min_days_back"]) for f in FREQUENCIES],
            )
            rows = conn.execute(
                "SELECT id, name FROM frequencies"
                " WHERE name = ANY(?)",
                ([f["name"] for f in FREQUENCIES],),
            ).fetchall()
        freq_id_map = {row["name"]: row["id"] for row in rows}
        logger.info("Seeded %d frequencies.", len(freq_id_map))

        # Domains
        with get_db() as conn:
            conn.execute_values(
                "INSERT INTO domains (name, slug, description)"
                " VALUES %s ON CONFLICT (slug) DO NOTHING",
                [
                    (d["name"], d["slug"], d["description"])
                    for d in DOMAINS
                ],
            )
            rows = conn.execute(
                "SELECT id, slug FROM domains WHERE slug = ANY(?)",
                ([d["slug"] for d in DOMAINS],),
            ).fetchall()
        domain_id_map = {row["slug"]: row["id"] for row in rows}
        logger.info("Seeded %d domains.", len(domain_id_map))

        # Sources
        source_rows = [
            (
                s["url"],
                domain_id_map[s["domain_slug"]],
                freq_id_map[s.get("frequency_name", "daily")],
                s["name"],
                s["description"],
                s.get("no_fetch", False),
                s.get("source_type", "rss"),
                json.dumps(s["config"]) if s.get("config") else None,
            )
            for s in SOURCES
        ]
        with get_db() as conn:
            cur = conn.execute_values(
                "INSERT INTO sources"
                " (url, domain_id, frequency_id, name, description,"
                " no_fetch, source_type, config)"
                " VALUES %s ON CONFLICT (url) DO NOTHING RETURNING id",
                source_rows,
            )
            inserted = len(cur.fetchall())
        skipped = len(source_rows) - inserted
        logger.info(
            "Seed complete: %d sources inserted,"
            " %d already existed.",
            inserted,
            skipped,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    seed()
