"""SMTP email sender using Python's built-in smtplib."""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import config

logger = logging.getLogger(__name__)


def _render_html(
    summaries: dict[str, str],
    categorised: dict[str, list[dict[str, Any]]],
) -> str:
    """Build the HTML email body."""
    parts: list[str] = [
        "<html><body>",
        "<h1>OCN Daily AI Intelligence Digest</h1>",
        "<hr>",
        "<h2>Category Summaries</h2>",
    ]

    for category in config.CATEGORIES:
        summary = summaries.get(category)
        if not summary:
            continue
        parts.append(f"<h3>{category}</h3>")
        parts.append(f"<p>{summary}</p>")

    parts += ["<hr>", "<h2>Articles</h2>"]

    for category in config.CATEGORIES:
        articles = categorised.get(category)
        if not articles:
            continue
        sorted_articles = sorted(
            articles,
            key=lambda a: a.get("composite_score", 0),
            reverse=True,
        )
        parts.append(f"<h3>{category}</h3><ul>")
        for a in sorted_articles:
            title = a.get("title") or a["url"]
            url = a["url"]
            score = a.get("composite_score", 0)
            label = a.get("label", "")
            parts.append(
                f'<li><a href="{url}">{title}</a> '
                f"<small>({label}, score: {score:.2f})</small></li>"
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
    msg["Subject"] = "OCN Daily AI Intelligence Digest"
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
