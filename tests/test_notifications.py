import reporting.notifications as notifications
from reporting.notifications import SMTPConfig, build_message, send_email, temp_password_email


def test_config_from_env_defaults_and_sender_fallback():
    config = SMTPConfig.from_env({"SMTP_USERNAME": "support@solvit.co.ke", "SMTP_PASSWORD": "x"})
    assert config.host == "smtp.office365.com"
    assert config.port == 587
    assert config.sender == "support@solvit.co.ke"  # falls back to username
    assert config.is_configured()


def test_config_not_configured_without_credentials():
    assert not SMTPConfig.from_env({}).is_configured()


def test_temp_password_email_contains_essentials():
    subject, body = temp_password_email("Peris Odhiambo", "podhiambo@solvit.co.ke", "Temp-123", app_url="https://dash")
    assert "Solvit" in subject
    assert "podhiambo@solvit.co.ke" in body
    assert "Temp-123" in body
    assert "set your own password" in body
    assert "https://dash" in body


def test_build_message_headers():
    message = build_message("support@solvit.co.ke", "x@y.com", "Hi", "Body")
    assert message["From"] == "support@solvit.co.ke"
    assert message["To"] == "x@y.com"
    assert message.get_content().strip() == "Body"


class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.started_tls = False
        self.logged_in = None
        self.sent = []
        _FakeSMTP.instances.append(self)

    def ehlo(self):
        pass

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, username, password):
        self.logged_in = (username, password)

    def send_message(self, message):
        self.sent.append(message)

    def quit(self):
        pass


def test_send_email_uses_tls_and_login(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(notifications.smtplib, "SMTP", _FakeSMTP)
    config = SMTPConfig(host="smtp.office365.com", port=587, username="support@solvit.co.ke",
                        password="secret", sender="support@solvit.co.ke", use_tls=True)
    send_email(config, "user@solvit.co.ke", "Hi", "Body")
    sent = _FakeSMTP.instances[-1]
    assert sent.started_tls is True
    assert sent.logged_in == ("support@solvit.co.ke", "secret")
    assert sent.sent[0]["To"] == "user@solvit.co.ke"
