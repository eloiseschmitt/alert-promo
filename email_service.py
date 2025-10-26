"""Email rendering and delivery helpers."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import List, Sequence

from jinja2 import Environment

from constants import DEFAULT_TIMEOUT
from models import ScanResult

__all__ = ["render_email_html", "send_email"]


def render_email_html(
    results: Sequence[ScanResult],
    generated_at: str,
    *,
    env: Environment,
    default_timeout: int = DEFAULT_TIMEOUT,
) -> str:
    template = env.get_template("email_report.html")
    return template.render(
        results=results,
        generated_at=generated_at,
        default_timeout=default_timeout,
    )


def send_email(subject: str, html_body: str, to_addrs: List[str]) -> None:
    """
    Uses ENV for SMTP settings:
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM
    """
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    mail_from = os.getenv("MAIL_FROM")

    if not smtp_host or not mail_from:
        raise RuntimeError("SMTP configuration missing: SMTP_HOST/MAIL_FROM")
    if not to_addrs:
        raise RuntimeError("No recipients provided to send_email")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(to_addrs)

    msg.set_content("Votre client email ne supporte pas le HTML. Ouvrez ce message en HTML pour voir le rapport.")
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.ehlo()
        try:
            server.starttls()
            server.ehlo()
        except smtplib.SMTPException:
            pass  # serveur déjà en TLS ou TLS non supporté
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.send_message(msg)
