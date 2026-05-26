"""SMTP email sender with signal-tier-aware HTML digest."""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import config

logger = logging.getLogger(__name__)

_TIER_BADGE: dict[str, str] = {
    "signal": '<span style="background:#1a7f37;color:#fff;padding:1px 6px;border-radius:3px;font-size:11px">signal</span>',
    "weak_signal": '<span style="background:#9a6700;color:#fff;padding:1px 6px;border-radius:3px;font-size:11px">weak</span>',
    "noise": '<span style="background:#888;color:#fff;padding:1px 6px;border-radius:3px;font-size:11px">noise</span>',
}

_MATERIALITY_STYLE: dict[str, str] = {
    "high": "font-weight:bold",
    "medium": "",
    "low": "color:#888",
    "none": "color:#aaa",
}

_SIGNAL_TIER_ORDER = {"signal": 0, "weak_signal": 1, "noise": 2}


def _render_html(
    summaries: dict[str, str],
    categorised: dict[str, list[dict[str, Any]]],
) -> str:
    parts: list[str] = [
        "<html><body style='font-family:sans-serif;max-width:800px;margin:auto'>",
        "<h1>OCN Daily Signal Intelligence Digest</h1>",
        "<hr>",
        "<h2>Category Summaries</h2>",
    ]

    for category in config.CATEGORIES:
        summary = summaries.get(category)
        if not summary:
            continue
        parts.append(f"<h3>{category}</h3>")
        parts.append(f"<p>{summary}</p>")

    parts += ["<hr>", "<h2>Articles by Category</h2>"]

    for category in config.CATEGORIES:
        articles = categorised.get(category)
        if not articles:
            continue

        sorted_articles = sorted(
            articles,
            key=lambda a: (
                _SIGNAL_TIER_ORDER.get(a.get("signal_detection", "noise"), 2),
                -float(a.get("signal_score") or 0),
            ),
        )

        parts.append(f"<h3>{category} <small>({len(sorted_articles)})</small></h3><ul>")
        for a in sorted_articles:
            title = a.get("title") or a.get("url", "")
            url = a.get("url", "#")
            tier = a.get("signal_detection", "noise")
            score = float(a.get("signal_score") or 0)
            materiality = a.get("materiality") or ""
            novelty = a.get("novelty") or ""
            entities = [e.get("name", "") for e in (a.get("entities") or [])]

            badge = _TIER_BADGE.get(tier, "")
            mat_style = _MATERIALITY_STYLE.get(materiality, "")
            star = " &#9733;" if novelty == "step_change" else ""

            entity_str = ""
            if entities:
                entity_str = (
                    f' <small style="color:#555">'
                    f'{", ".join(entities[:4])}</small>'
                )

            meta = f"score {score:.2f}"
            if materiality and materiality != "none":
                meta += f", {materiality} materiality"
            if novelty:
                meta += f", {novelty}"

            parts.append(
                f'<li style="{mat_style};margin-bottom:4px">'
                f'{badge} <a href="{url}">{title}</a>{star}{entity_str} '
                f'<small style="color:#666">({meta})</small>'
                f"</li>"
            )
        parts.append("</ul>")

    parts.append("</body></html>")
    return "\n".join(parts)


def send_digest(
    summaries: dict[str, str],
    categorised: dict[str, list[dict[str, Any]]],
) -> None:
    """Send the daily digest email via SMTP."""
    html_body = _render_html(summaries, categorised)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "OCN Daily Signal Intelligence Digest"
    msg["From"] = config.SMTP_FROM
    msg["To"] = ", ".join(config.EMAIL_RECIPIENTS)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.sendmail(
            config.SMTP_FROM,
            config.EMAIL_RECIPIENTS,
            msg.as_string(),
        )

    logger.info(
        "Digest email sent to %d recipients via %s",
        len(config.EMAIL_RECIPIENTS),
        config.SMTP_HOST,
    )
