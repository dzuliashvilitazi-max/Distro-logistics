import asyncio

import email_service


def test_send_email_uses_resend_html_sender_and_attachments(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("EMAIL_FROM", "Distro Logistics <onboarding@distrologistics.ge>")
    monkeypatch.setattr(email_service.resend, "api_key", "", raising=False)
    sent = {}

    async def fake_send(params):
        sent.update(params)
        return {"id": "email-test-id"}

    monkeypatch.setattr(email_service.resend.Emails, "send_async", fake_send)
    result = asyncio.run(email_service.send_email(
        to="recipient@example.com",
        subject="Verification code",
        html="<p>Your code is <strong>123456</strong></p>",
        attachments=[{"filename": "invoice.pdf", "content": b"pdf-bytes", "content_type": "application/pdf"}],
    ))

    assert result == "resend"
    assert email_service.resend.api_key == "re_test_key"
    assert sent["from"] == "Distro Logistics <onboarding@distrologistics.ge>"
    assert sent["to"] == ["recipient@example.com"]
    assert sent["html"] == "<p>Your code is <strong>123456</strong></p>"
    assert sent["attachments"] == [{"filename": "invoice.pdf", "content": list(b"pdf-bytes")}]


def test_send_email_accepts_verified_sender_in_legacy_name_setting(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    monkeypatch.setenv("EMAIL_FROM_NAME", "Distro Logistics <onboarding@distrologistics.ge>")
    sent = {}

    async def fake_send(params):
        sent.update(params)

    monkeypatch.setattr(email_service.resend.Emails, "send_async", fake_send)
    asyncio.run(email_service.send_email(
        to="recipient@example.com", subject="Test", html="<p>Test</p>",
    ))

    assert sent["from"] == "Distro Logistics <onboarding@distrologistics.ge>"


def test_try_send_email_reports_missing_resend_key(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)

    sent, reason = asyncio.run(email_service.try_send_email_detailed(
        to="recipient@example.com", subject="Test", html="<p>Test</p>",
    ))

    assert sent is False
    assert "RESEND_API_KEY" in reason


def test_try_send_email_reports_resend_failure(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")

    async def fake_send(params):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(email_service.resend.Emails, "send_async", fake_send)
    sent, reason = asyncio.run(email_service.try_send_email_detailed(
        to="recipient@example.com", subject="Test", html="<p>Test</p>",
    ))

    assert sent is False
    assert reason == "RuntimeError: provider unavailable"