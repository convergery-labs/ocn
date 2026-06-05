"""Signal-detection-agent category taxonomy.

Single source of truth for allowed article categories.
Mirrors the 19-category AI Economy Universe taxonomy in research-universe.

To update categories: edit ALLOWED_CATEGORIES below.
The classifier validates every LLM response against this set.
"""

ALLOWED_CATEGORIES: set[str] = {
    'Raw Materials & Critical Minerals',
    'Energy & Grid Infrastructure',
    'Nuclear & Advanced Energy',
    'Semiconductor Manufacturing',
    'Compute Hardware & Edge Systems',
    'Networking, Optical & Interconnect',
    'Data Centers & Physical Infrastructure',
    'Telecom & Connectivity',
    'Cloud & Compute Platforms',
    'AI Software Infrastructure',
    'AI Data Infrastructure',
    'AI Models & Intelligence Layer',
    'Robotics & Physical AI',
    'Quantum Computing & Sensing',
    'Life Sciences & Healthcare AI',
    'Defense, Aerospace & Sovereign AI',
    'Financial Infrastructure & AI Capital',
    'Water & Resource Infrastructure',
    'Applications & Digital Economy',
}
