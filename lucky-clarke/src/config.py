"""Configuration: categories, recipients, and environment variables."""
import os

CATEGORIES: list[str] = [
    "AI Core Platforms, Software, and Security",
    "AI Compute, Semiconductors, Design Tools, and Materials",
    "Networking, Optical, and Connectivity Systems",
    "Data, Memory, Storage, and Server Systems",
    "AI Infrastructure, Data Centers, Power, and Cooling",
    "Construction, Engineering, and Electrical Services",
    "Energy-Rare Earth Universe",
    "Aero-Defense-Orbital Space",
    "Robotics, Autonomous Systems, and Physical AI",
    "Quantum and Advanced Compute",
    "AI Compute Hosting, Neocloud, and Edge AI",
    "Optical Communications Value Chain",
]

EMAIL_RECIPIENTS: list[str] = [
    "gunjan@opengrowth.com",
    "karan@nasiko.com",
    "kajal.nain@opengrowth.com",
    "ayushi.shah@opengrowth.com",
    "serhii.krutyholova@gmail.com",
    "aditya.jaiswal@opengrowth.com",
    "wasikul.islam@cern.ch",
]

SIGNAL_DETECTION_URL: str = os.environ.get(
    "SIGNAL_DETECTION_URL", "http://localhost:8002"
)
LUCKY_CLARKE_URL: str = os.environ.get(
    "LUCKY_CLARKE_URL", "http://localhost:8005"
)
SIGNAL_CALLER_SUB: int = int(
    os.environ.get("SIGNAL_CALLER_SUB", "1")
)
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.environ.get(
    "OPENROUTER_MODEL", "openai/gpt-4o-mini"
)
SMTP_HOST: str = os.environ.get("SMTP_HOST", "")
SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER: str = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD: str = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM: str = os.environ.get("SMTP_FROM", "")

POLL_INTERVAL_SECONDS: int = 30
POLL_MAX_ATTEMPTS: int = 120
