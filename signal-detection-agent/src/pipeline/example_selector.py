"""Dynamic example selector for the v1 signal classifier prompt.

Parses all 75 labelled examples out of the v1 system prompt at import time,
then for each article selects a small targeted subset:
  - 3 examples matching the article's predicted category
  - 2 noise examples (always included to reinforce conservatism)
  - 2 signal/weak_signal wildcard examples from other categories
  - 1 edge-case example (stock price, governance, academic) if article text hints at one

This keeps the injected examples to ~8 vs the full 75, saving ~13,000 input
tokens per article while retaining the full rules/definitions/schema section.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Example:
    number: int
    label: str          # "signal" | "weak_signal" | "noise"
    category: str       # exact category name
    keywords: list[str] # lowercased terms extracted from the article text
    raw: str            # the full example block as it appears in the prompt


# ---------------------------------------------------------------------------
# Category → keyword signals used for fast article routing
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Raw Materials & Critical Minerals": [
        "rare earth", "lithium", "copper", "uranium", "mineral", "mining",
        "aluminum", "cobalt", "nickel", "graphite", "pcb", "substrate",
    ],
    "Energy & Grid Infrastructure": [
        "power", "energy", "grid", "utility", "gas", "renewable", "solar",
        "wind", "electricity", "interconnect", "transmission", "generator",
        "permitting", "pjm", "data center power",
    ],
    "Nuclear & Advanced Energy": [
        "nuclear", "smr", "reactor", "constellation energy", "three mile",
        "oklo", "kairos", "nrc", "long-duration storage",
    ],
    "Semiconductor Manufacturing": [
        "chip", "semiconductor", "gpu", "tsmc", "nvidia", "amd", "intel",
        "wafer", "foundry", "hbm", "memory", "accelerator", "fab", "node",
        "blackwell", "gaudi", "packaging", "eda",
    ],
    "Compute Hardware & Edge Systems": [
        "server", "rack", "appliance", "supermicro", "dell", "edge compute",
        "ai server", "oem", "odm", "embedded", "dgx", "storage system",
    ],
    "Networking, Optical & Interconnect": [
        "optical", "transceiver", "infiniband", "fiber", "interconnect",
        "switch", "arista", "coherent", "networking", "photonics", "400g",
        "800g", "1.6t",
    ],
    "Data Centers & Physical Infrastructure": [
        "data center", "colocation", "reit", "liquid cooling", "cooling",
        "hvac", "thermal", "equinix", "digitalbridge", "campus", "facility",
        "construction", "hyperscale",
    ],
    "Telecom & Connectivity": [
        "telecom", "5g", "starlink", "satellite", "nokia", "ericsson",
        "t-mobile", "at&t", "spectrum", "ran", "backhaul", "wireless",
    ],
    "Cloud & Compute Platforms": [
        "azure", "aws", "google cloud", "cloud", "hyperscaler", "coreweave",
        "neocloud", "gpu cloud", "compute platform", "capex", "data center capex",
    ],
    "AI Software Infrastructure": [
        "mlops", "inference", "vllm", "llmops", "agent framework", "vector",
        "database", "devops", "cybersecurity", "siem", "saas", "middleware",
        "observability", "developer tool", "coding tool", "copilot",
    ],
    "AI Data Infrastructure": [
        "data labeling", "annotation", "synthetic data", "training data",
        "scale ai", "data pipeline", "dataset", "clearview",
    ],
    "AI Models & Intelligence Layer": [
        "model", "llm", "foundation model", "openai", "anthropic", "google deepmind",
        "mistral", "gpt", "claude", "gemini", "benchmark", "frontier", "chatgpt",
        "character.ai", "stability ai", "api pricing", "reasoning", "ipo", "valuation",
        "model provider", "token", "training run", "pre-training",
    ],
    "Robotics & Physical AI": [
        "robot", "humanoid", "autonomous", "drone", "adas", "ev ", "electric vehicle",
        "figure ai", "boston dynamics", "physical ai", "factory automation",
    ],
    "Quantum Computing & Sensing": [
        "quantum", "qubit", "ionq", "ibm quantum", "qkd", "post-quantum",
        "gate fidelity",
    ],
    "Life Sciences & Healthcare AI": [
        "drug discovery", "genomics", "medical imaging", "clinical ai",
        "protein", "alphafold", "pharma", "fda", "healthcare ai", "biotech",
        "recursion", "eli lilly", "cancer",
    ],
    "Defense, Aerospace & Sovereign AI": [
        "defense", "military", "palantir", "l3harris", "dod", "air force",
        "army", "navy", "geospatial", "isr", "sovereign ai", "space launch",
        "aerospace",
    ],
    "Financial Infrastructure & AI Capital": [
        "fintech", "jpmorgan", "visa", "payment", "fraud detection", "banking ai",
        "financial ai", "investment vehicle", "project finance",
    ],
    "Water & Resource Infrastructure": [
        "water", "recycling", "waste heat", "veolia", "cooling water", "resource",
    ],
    "Applications & Digital Economy": [
        "consumer ai", "retail", "marketing", "gaming", "agtech",
        "digital economy", "vertical ai", "small business", "startup",
        "legal ai", "harvey", "app", "smb",
    ],
}

# Edge-case hint patterns → example numbers that best illustrate the rule
_EDGE_CASE_EXAMPLES: list[tuple[list[str], list[int]]] = [
    (["stock", "share price", "surge", "all-time high", "52-week"], [33, 34, 37]),
    (["governance", "commission", "study group", "encyclical", "ethics", "consultation"], [11, 13, 14]),
    (["scholarship", "grant", "university", "research award", "academic"], [6, 16, 61]),
    (["fundrais", "in talks", "exploring", "seeking capital", "series"], [12, 67]),
    (["short-seller", "fraud", "misconduct", "allegation"], [20, 22]),
    (["layoff", "restructur", "headcount", "job cut"], [19, 22, 30]),
    (["permitting", "injunction", "regulatory action", "enforcement"], [20, 40, 59]),
    (["bankruptcy", "shutdown", "wind-down", "discontinu"], [21, 24, 28, 48]),
]


def _predict_category(text: str) -> str | None:
    """Return the category with the most keyword hits, or None."""
    low = text.lower()
    best_cat: str | None = None
    best_score = 0
    for cat, kws in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in low)
        if score > best_score:
            best_score = score
            best_cat = cat
    return best_cat if best_score > 0 else None


def _edge_case_example_numbers(text: str) -> list[int]:
    low = text.lower()
    numbers: list[int] = []
    for hints, ex_nums in _EDGE_CASE_EXAMPLES:
        if any(h in low for h in hints):
            numbers.extend(ex_nums)
    return numbers


def parse_examples(prompt_text: str) -> list[Example]:
    """Extract all labelled examples from the v1 prompt."""
    # Each example starts with a line like:
    # "Example N, Signal, high materiality, Category Name:"
    # or "Example N, Noise:"
    header_re = re.compile(
        r"^Example\s+(\d+),\s*(Signal|Weak signal|Noise)"
        r"(?:,\s*(?:high|medium|low)\s+materiality)?"
        r"(?:,\s*([^:]+))?:",
        re.IGNORECASE | re.MULTILINE,
    )

    matches = list(header_re.finditer(prompt_text))
    examples: list[Example] = []

    for i, m in enumerate(matches):
        num = int(m.group(1))
        raw_label = m.group(2).strip().lower().replace(" ", "_")
        raw_cat = (m.group(3) or "").strip()

        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(prompt_text)
        raw = prompt_text[start:end].rstrip()

        # Extract keywords from the example's Article and Output text
        example_body = raw.lower()
        keywords = [
            kw for kws in CATEGORY_KEYWORDS.values()
            for kw in kws if kw in example_body
        ]

        examples.append(Example(
            number=num,
            label=raw_label,
            category=raw_cat,
            keywords=keywords,
            raw=raw,
        ))

    return examples


class ExampleSelector:
    """Holds all parsed examples and selects a targeted subset per article."""

    def __init__(self, examples: list[Example]) -> None:
        self._all = examples
        self._by_number: dict[int, Example] = {e.number: e for e in examples}
        self._noise = [e for e in examples if e.label == "noise"]
        self._signal_weak = [e for e in examples if e.label in ("signal", "weak_signal")]

    def select(self, article_text: str, n_category: int = 4, n_noise: int = 2, n_wildcard: int = 2) -> list[Example]:
        """Select a targeted subset of examples for this article.

        Strategy:
        1. Predict the article's likely category from keywords.
        2. Pick up to n_category examples whose category matches (balanced signal/noise).
        3. Pick n_noise fixed generic noise examples (reinforce conservatism).
        4. Pick n_wildcard signal/weak_signal from DIFFERENT categories (one per category).
        5. Add any edge-case examples triggered by article text hints.
        All examples are deduplicated and returned in original prompt order.
        """
        low = article_text.lower()
        predicted_cat = _predict_category(low)
        selected_nums: set[int] = set()

        # 1. Category-matched examples — up to n_category, balanced signal/noise
        if predicted_cat:
            cat_examples = [
                e for e in self._all
                if predicted_cat.lower() in e.category.lower()
            ]
            signals_in_cat = [e for e in cat_examples if e.label in ("signal", "weak_signal")]
            noise_in_cat = [e for e in cat_examples if e.label == "noise"]
            take_signal = min(len(signals_in_cat), max(2, n_category - 1))
            take_noise_cat = min(len(noise_in_cat), n_category - take_signal)
            for e in signals_in_cat[:take_signal]:
                selected_nums.add(e.number)
            for e in noise_in_cat[:take_noise_cat]:
                selected_nums.add(e.number)

        # 2. Fixed generic noise anchors (ex 5=think-piece, 6=small grant, 13=opinion)
        for num in [5, 6, 13][:n_noise]:
            selected_nums.add(num)

        # 3. Wildcard signal/weak_signal — one from each of n_wildcard DISTINCT categories
        #    that are different from the predicted category, to provide cross-category coverage
        seen_wildcard_cats: set[str] = set()
        if predicted_cat:
            seen_wildcard_cats.add(predicted_cat.lower())
        for e in self._signal_weak:
            if len(seen_wildcard_cats) - (1 if predicted_cat else 0) >= n_wildcard:
                break
            if e.number in selected_nums:
                continue
            e_cat_low = e.category.lower()
            if e_cat_low not in seen_wildcard_cats:
                selected_nums.add(e.number)
                seen_wildcard_cats.add(e_cat_low)

        # 4. Edge-case examples triggered by article content
        for num in _edge_case_example_numbers(low):
            selected_nums.add(num)

        # Return in original prompt order (by example number)
        return sorted(
            [self._by_number[n] for n in selected_nums if n in self._by_number],
            key=lambda e: e.number,
        )


def build_static_system_prompt(base_prompt: str) -> str:
    """Return the static portion of the v1 prompt (everything up to and including
    the EXAMPLES header, without any example blocks).

    This is always identical across articles, so it gets a stable cache key
    when used with cache_control. Dynamic examples are injected into the user
    message instead via build_examples_block().
    """
    examples_header_re = re.compile(r"(={20,}\s*\nEXAMPLES\s*\n={20,})", re.IGNORECASE)
    m = examples_header_re.search(base_prompt)
    if not m:
        return base_prompt
    return base_prompt[: m.end()]


def build_examples_block(selector: ExampleSelector, article_text: str) -> str:
    """Return a formatted block of selected examples to inject into the user message."""
    selected = selector.select(article_text)
    if not selected:
        return ""
    examples_text = "\n\n".join(e.raw for e in selected)
    return f"Reference examples:\n\n{examples_text}"


def build_prompt_with_selected_examples(
    base_prompt: str,
    selector: ExampleSelector,
    article_text: str,
) -> str:
    """Return the v1 system prompt with only the selected examples injected.

    Replaces the full EXAMPLES section (everything after the
    '====...====' separator before 'Example 1') with the selected subset.
    """
    # Split prompt into preamble (everything up to and including the EXAMPLES header)
    # and the examples block.
    examples_header_re = re.compile(r"(={20,}\s*\nEXAMPLES\s*\n={20,})", re.IGNORECASE)
    m = examples_header_re.search(base_prompt)
    if not m:
        # Fallback: return unchanged prompt if we can't find the split point
        return base_prompt

    preamble = base_prompt[: m.end()]

    selected = selector.select(article_text)
    examples_text = "\n\n".join(e.raw for e in selected)

    # Keep the final "Return strict JSON only." line from the original prompt
    footer = "\n\nReturn strict JSON only."

    return preamble + "\n\n" + examples_text + footer
