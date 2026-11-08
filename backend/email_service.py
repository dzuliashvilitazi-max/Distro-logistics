"""Resend email delivery (invoices, reminders, OTP) for Distro Logistics."""
import os
import re
import ipaddress
import logging
from html import escape
from html.parser import HTMLParser
from email.utils import formataddr, parseaddr
from urllib.parse import urlparse
import resend
from resend.exceptions import ResendError

logger = logging.getLogger("distro.email")

_EMAIL_FROM_NAME_SETTING = os.environ.get("EMAIL_FROM_NAME", "Distro Logistics").strip()
EMAIL_FROM_NAME, _ = parseaddr(_EMAIL_FROM_NAME_SETTING)
EMAIL_FROM_NAME = EMAIL_FROM_NAME or _EMAIL_FROM_NAME_SETTING or "Distro Logistics"
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


def _sender_header() -> str:
    configured_from = os.environ.get("EMAIL_FROM", "").strip()
    if configured_from:
        display_name, address = parseaddr(configured_from)
        return formataddr((display_name or EMAIL_FROM_NAME, address)) if "@" in address else formataddr((EMAIL_FROM_NAME, configured_from))

    configured_name, configured_address = parseaddr(
        os.environ.get("EMAIL_FROM_NAME", _EMAIL_FROM_NAME_SETTING).strip(),
    )
    if "@" in configured_address:
        return formataddr((configured_name or EMAIL_FROM_NAME, configured_address))
    return formataddr((EMAIL_FROM_NAME, "onboarding@distrologistics.ge"))


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


async def send_email(*, to: str, subject: str, html: str, attachments: list[dict] | None = None,
                     ) -> str:
    """Send HTML email via Resend; attachments use filename/content/content_type dictionaries."""
    _assert_safe_email(subject, html)
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not configured.")
    resend.api_key = api_key
    params = {
        "from": _sender_header(),
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if EMAIL_REPLY_TO:
        params["reply_to"] = EMAIL_REPLY_TO
    if attachments:
        params["attachments"] = [
            {"filename": item["filename"], "content": list(item["content"])}
            for item in attachments
        ]
    await resend.Emails.send_async(params)
    return "resend"


async def try_send_email_detailed(*, to: str, subject: str, html: str,
                                  attachments: list[dict] | None = None) -> tuple[bool, str]:
    """Returns (ok, reason). Logs the exact failure cause."""
    if not os.environ.get("RESEND_API_KEY", "").strip():
        reason = "ელფოსტა არ არის გამართული: მიუთითეთ RESEND_API_KEY backend-ის გარემოს ცვლადებში."
        logger.warning(reason)
        return False, reason
    try:
        await send_email(to=to, subject=subject, html=html, attachments=attachments)
        logger.info("Email sent to %s via Resend: %s", to, subject)
        return True, ""
    except ResendError as error:
        reason = f"Resend API error: {error}"
    except Exception as error:
        reason = f"{type(error).__name__}: {error}"
    logger.error("Email send failed to %s: %s", to, reason)
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
