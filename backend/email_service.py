"""SMTP email sending (invoices, reminders, OTP) for Distro Logistics."""
import os
import re
import base64
import asyncio
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr
import ipaddress
import logging
import httpx
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

logger = logging.getLogger("distro.email")

EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "Distro Logistics")
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "")

_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan(); scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} != real link host {real!r} (G3)")


def _smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"))


def _env_smtp() -> dict:
    return {"host": os.environ.get("SMTP_HOST", ""), "port": int(os.environ.get("SMTP_PORT", "587")),
            "user": os.environ.get("SMTP_USER", ""), "password": os.environ.get("SMTP_PASSWORD", ""),
            "from": os.environ.get("SMTP_FROM", "")}


def _build_message(to: str, subject: str, html: str, attachments: list[dict] | None, cfg: dict | None = None) -> EmailMessage:
    cfg = cfg or _env_smtp()
    sender = cfg.get("from") or cfg["user"]
    msg = EmailMessage()
    msg["From"] = formataddr((EMAIL_FROM_NAME, sender))
    msg["To"] = to
    msg["Subject"] = subject
    if EMAIL_REPLY_TO:
        msg["Reply-To"] = EMAIL_REPLY_TO
    msg.set_content(re.sub(r"<[^>]+>", " ", html))
    msg.add_alternative(html, subtype="html")
    for a in attachments or []:
        maintype, _, subtype = a.get("content_type", "application/pdf").partition("/")
        msg.add_attachment(a["content"], maintype=maintype, subtype=subtype or "octet-stream", filename=a["filename"])
    return msg


def _smtp_send(msg: EmailMessage, cfg: dict | None = None) -> None:
    cfg = cfg or _env_smtp()
    host, port, user, password = cfg["host"], int(cfg["port"]), cfg["user"], cfg["password"]
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port, timeout=30)
    with server:
        if port != 465:
            server.starttls(context=ssl.create_default_context())
        server.login(user, password)
        server.send_message(msg)


async def send_email(*, to: str, subject: str, html: str, attachments: list[dict] | None = None,
                     smtp: dict | None = None) -> str | None:
    """attachments: [{"filename": str, "content": bytes, "content_type": str}]"""
    _assert_safe_email(subject, html)
    if not (smtp or _smtp_configured()):
        raise RuntimeError("SMTP is not configured (SMTP_HOST, SMTP_USER, SMTP_PASSWORD).")
    await asyncio.to_thread(_smtp_send, _build_message(to, subject, html, attachments, smtp), smtp)
    return "smtp"


def describe_email_error(e: Exception, cfg: dict | None = None) -> str:
    cfg = cfg or _env_smtp()
    host = cfg.get("host", "")
    port = str(cfg.get("port", "587"))
    if isinstance(e, smtplib.SMTPAuthenticationError):
        hint = " (Gmail-ისთვის გამოიყენეთ App Password და ჩართეთ 2-Step Verification)" if "gmail" in host else ""
        return f"SMTP Authentication Failed ({e.smtp_code}): ავტორიზაცია ვერ მოხერხდა - შეამოწმეთ SMTP_USER/SMTP_PASSWORD{hint}"
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return f"SMTP: მიმღების მისამართი უარყოფილია: {e.recipients}"
    if isinstance(e, smtplib.SMTPSenderRefused):
        return f"SMTP: გამგზავნის მისამართი უარყოფილია ({e.smtp_code}) - შეამოწმეთ SMTP_FROM"
    if isinstance(e, smtplib.SMTPConnectError | smtplib.SMTPServerDisconnected):
        return f"SMTP: სერვერთან კავშირი გაწყდა/ვერ დამყარდა ({host}:{port}): {e}"
    if isinstance(e, ssl.SSLError):
        return f"SMTP: SSL/TLS შეცდომა - შეამოწმეთ პორტი ({host}:{port}; 465=SSL, 587=STARTTLS): {e}"
    if isinstance(e, TimeoutError | socket.timeout):
        return f"SMTP: დრო ამოიწურა ({host}:{port}) - პორტი დაბლოკილია ან მისამართი არასწორია"
    if isinstance(e, socket.gaierror):
        return f"SMTP: ჰოსტი ვერ მოიძებნა: {host!r} ({e})"
    if isinstance(e, OSError):
        return f"SMTP: ქსელური შეცდომა ({host}:{port}): {e}"
    if isinstance(e, smtplib.SMTPException):
        return f"SMTP შეცდომა: {e}"
    return f"{type(e).__name__}: {e}"


async def try_send_email_detailed(*, to: str, subject: str, html: str,
                                  attachments: list[dict] | None = None,
                                  smtp: dict | None = None) -> tuple[bool, str]:
    """Returns (ok, reason). Logs the exact failure cause."""
    if not smtp and not _smtp_configured():
        reason = "ელფოსტა არ არის გამართული: დააყენეთ SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD (backend/.env)"
        logger.warning(reason)
        return False, reason
    try:
        await send_email(to=to, subject=subject, html=html, attachments=attachments, smtp=smtp)
        logger.info(f"Email sent to {to} via SMTP: {subject}")
        return True, ""
    except Exception as e:
        reason = describe_email_error(e, smtp)
    logger.error(f"Email send failed to {to}: {reason}")
    return False, reason


async def try_send_email(*, to: str, subject: str, html: str, attachments: list[dict] | None = None) -> bool:
    """Non-raising wrapper for background/cron use. Logs and returns success flag."""
    ok, _ = await try_send_email_detailed(to=to, subject=subject, html=html, attachments=attachments)
    return ok


def _app_link() -> str:
    base = (APP_BASE_URL or "").rstrip("/")
    return base if base.startswith("https://") else ""


def _wrap(inner: str) -> str:
    link = _app_link()
    cta = (f'<p style="margin:24px 0"><a href="{escape(link)}" '
           f'style="background:#0f766e;color:#ffffff;padding:11px 22px;border-radius:8px;'
           f'text-decoration:none;font-weight:bold;display:inline-block">Open Distro Logistics</a></p>') if link else ""
    return (f'<table role="presentation" width="100%" style="background:#f4f5f7;padding:24px">'
            f'<tr><td align="center">'
            f'<table role="presentation" width="600" style="background:#ffffff;border-radius:12px;'
            f'font-family:Arial,Helvetica,sans-serif;color:#111827;overflow:hidden">'
            f'<tr><td style="background:#0f766e;padding:20px 28px">'
            f'<span style="color:#ffffff;font-size:18px;font-weight:bold">Distro Logistics</span>'
            f'<span style="color:#99f6e4;font-size:11px;letter-spacing:1px;display:block;text-transform:uppercase">'
            f'B2B Distribution</span></td></tr>'
            f'<tr><td style="padding:28px">{inner}{cta}'
            f'<p style="font-size:12px;color:#888;margin-top:28px;border-top:1px solid #eee;padding-top:16px">'
            f'Sent by {escape(EMAIL_FROM_NAME)}. This is a commission billing notice for your supplier account. '
            f'We never ask for your password or card details by email.</p>'
            f'</td></tr></table></td></tr></table>')


def _money(v) -> str:
    return f"\u20be{float(v):,.2f}"


def _rows(inv: dict) -> str:
    out = ""
    for li in inv.get("line_items", []):
        out += (f'<tr><td style="padding:6px 8px;border-bottom:1px solid #eee;font-size:13px">{escape(str(li.get("order_no","")))}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid #eee;font-size:13px">{escape(str(li.get("date","")))}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid #eee;font-size:13px;text-align:right">{_money(li.get("order_total",0))}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid #eee;font-size:13px;text-align:right">{_money(li.get("commission",0))}</td></tr>')
    return out


def otp_email_html(code: str, name: str = "") -> str:
    inner = (
        f'<p style="font-size:15px">Hello{(" " + escape(name)) if name else ""},</p>'
        f'<p>Use the verification code below to activate your Distro Logistics account:</p>'
        f'<p style="margin:24px 0;text-align:center">'
        f'<span style="display:inline-block;background:#f0fdfa;border:1px solid #99f6e4;border-radius:10px;'
        f'padding:14px 28px;font-size:30px;font-weight:bold;letter-spacing:8px;color:#0f766e">{escape(code)}</span></p>'
        f'<p style="font-size:13px;color:#6b7280">This code expires in 10 minutes. If you did not create an account, '
        f'you can safely ignore this email.</p>'
    )
    return _wrap(inner)


def password_reset_otp_email_html(code: str, name: str = "") -> str:
    inner = (
        f'<p style="font-size:15px">Hello{(" " + escape(name)) if name else ""},</p>'
        '<p>Use this one-time code to reset your Distro Logistics password:</p>'
        f'<p style="margin:24px 0;text-align:center"><span style="display:inline-block;background:#f0fdfa;'
        f'border:1px solid #99f6e4;border-radius:10px;padding:14px 28px;font-size:30px;font-weight:bold;'
        f'letter-spacing:8px;color:#0f766e">{escape(code)}</span></p>'
        '<p style="font-size:13px;color:#6b7280">This code expires in 10 minutes. '
        'If you did not request a password reset, you can safely ignore this email.</p>'
    )
    return (
        '<table role="presentation" width="100%" style="background:#f4f5f7;padding:24px">'
        '<tr><td align="center"><table role="presentation" width="600" '
        'style="background:#ffffff;border-radius:12px;font-family:Arial,Helvetica,sans-serif;color:#111827;overflow:hidden">'
        '<tr><td style="background:#0f766e;padding:20px 28px;color:#ffffff;font-size:18px;font-weight:bold">'
        'Distro Logistics</td></tr><tr><td style="padding:28px">'
        f'{inner}<p style="font-size:12px;color:#888;margin-top:28px;border-top:1px solid #eee;padding-top:16px">'
        f'Sent by {escape(EMAIL_FROM_NAME)}. We never ask for your password by email.</p>'
        '</td></tr></table></td></tr></table>'
    )


def invoice_email_html(inv: dict) -> str:
    inner = (
        f'<p style="font-size:15px">Dear {escape(inv.get("supplier_name",""))},</p>'
        f'<p>Your commission invoice <strong>{escape(inv.get("invoice_no",""))}</strong> for '
        f'<strong>{escape(inv.get("period_label",""))}</strong> has been generated.</p>'
        f'<table role="presentation" width="100%" style="border-collapse:collapse;margin:12px 0">'
        f'<tr style="background:#f0fdfa"><th align="left" style="padding:8px;font-size:12px">Order</th>'
        f'<th align="left" style="padding:8px;font-size:12px">Delivered</th>'
        f'<th align="right" style="padding:8px;font-size:12px">Order Total</th>'
        f'<th align="right" style="padding:8px;font-size:12px">Commission</th></tr>'
        f'{_rows(inv)}'
        f'<tr><td colspan="3" style="padding:10px 8px;text-align:right;font-weight:bold">Total Due</td>'
        f'<td style="padding:10px 8px;text-align:right;font-weight:bold;color:#0f766e">{_money(inv.get("amount",0))}</td></tr>'
        f'</table>'
        f'<p style="font-size:14px"><strong>Payment due by {escape(inv.get("due_label",""))}</strong> '
        f'(5 calendar days). Please transfer to:</p>'
        f'<p style="font-size:14px;background:#f9fafb;padding:12px;border-radius:8px">'
        f'{escape(inv.get("issuer_name",""))}<br>Tax ID: {escape(inv.get("issuer_tax_id",""))}<br>'
        f'IBAN: {escape(inv.get("issuer_iban",""))}</p>'
        + (f'<p style="margin:16px 0"><a href="{escape(inv["payment_link"])}" style="background:#0f766e;color:#fff;'
           f'padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:bold">Pay online</a></p>'
           if inv.get("payment_link") else "") +
        f'<p style="font-size:13px;color:#6b7280">Download the official PDF invoice from the '
        f'Invoices &amp; Billing section of your supplier dashboard. If the invoice remains unpaid after the '
        f'due date, new order acceptance will be temporarily paused until payment is reconciled.</p>'
    )
    return _wrap(inner)


def reminder_email_html(inv: dict) -> str:
    inner = (
        f'<p style="font-size:15px">Dear {escape(inv.get("supplier_name",""))},</p>'
        f'<p style="color:#b91c1c;font-weight:bold">Payment reminder: invoice {escape(inv.get("invoice_no",""))} is overdue.</p>'
        f'<p>Your commission invoice for <strong>{escape(inv.get("period_label",""))}</strong> of '
        f'<strong>{_money(inv.get("amount",0))}</strong> was due on <strong>{escape(inv.get("due_label",""))}</strong> '
        f'and remains unpaid.</p>'
        f'<p style="font-size:14px;background:#f9fafb;padding:12px;border-radius:8px">'
        f'{escape(inv.get("issuer_name",""))}<br>Tax ID: {escape(inv.get("issuer_tax_id",""))}<br>'
        f'IBAN: {escape(inv.get("issuer_iban",""))}</p>'
        f'<p style="font-size:13px;color:#6b7280">New order acceptance on your account is paused until this invoice '
        f'is marked paid. Please settle the outstanding amount at the earliest.</p>'
    )
    return _wrap(inner)
