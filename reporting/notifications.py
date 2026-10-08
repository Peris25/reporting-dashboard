"""Send account emails over SMTP (e.g. Microsoft 365).

Kept dependency-free (standard-library smtplib) and importable without touching
Streamlit or the database, so it can be reused by the seeding script today and an
admin page later. Credentials come from the environment, never from code.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    sender: str
    use_tls: bool = True

    @classmethod
    def from_env(cls, env):
        return cls(
            host=env.get("SMTP_HOST", "smtp.office365.com"),
            port=int(env.get("SMTP_PORT", "587") or 587),
            username=env.get("SMTP_USERNAME", ""),
            password=env.get("SMTP_PASSWORD", ""),
            sender=env.get("SMTP_FROM") or env.get("SMTP_USERNAME", ""),
            use_tls=str(env.get("SMTP_USE_TLS", "true")).lower() == "true",
        )

    def is_configured(self):
        return bool(self.host and self.sender and self.username and self.password)


def build_message(sender, to, subject, body):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return message


def send_email(config, to, subject, body):
    """Send one plain-text email. Raises on failure so the caller can report it."""
    message = build_message(config.sender, to, subject, body)
    server = smtplib.SMTP(config.host, config.port, timeout=30)
    try:
        server.ehlo()
        if config.use_tls:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if config.username and config.password:
            server.login(config.username, config.password)
        server.send_message(message)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def temp_password_email(display_name, username, temp_password, *, app_url=""):
    """Subject and body for a temporary-password notice."""
    subject = "Your Solvit Reporting Dashboard access"
    lines = [
        f"Hello {display_name or username},",
        "",
        "An account has been set up for you on the Solvit Reporting Dashboard.",
        "",
        f"    Username: {username}",
        f"    Temporary password: {temp_password}",
        "",
        "You will be asked to set your own password the first time you sign in, "
        "so this temporary password stops working after that.",
    ]
    if app_url:
        lines += ["", f"Sign in here: {app_url}"]
    lines += ["", "If you did not expect this email, please contact IT."]
    return subject, "\n".join(lines)
