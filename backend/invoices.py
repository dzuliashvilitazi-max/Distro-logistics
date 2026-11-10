"""Georgian invoice PDF generation."""
from io import BytesIO
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfdoc import PDFString
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

TEAL = colors.HexColor("#0f766e")
LIGHT = colors.HexColor("#f0fdfa")
GREY = colors.HexColor("#6b7280")
FONT_NAME = "NotoSansGeorgian"
FONT_PATH = Path(__file__).resolve().parent / "assets" / "fonts" / "NotoSansGeorgian.ttf"

if not FONT_PATH.is_file():
    raise FileNotFoundError(f"Georgian PDF font not found: {FONT_PATH}")
if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))
pdfmetrics.registerFontFamily(
    FONT_NAME, normal=FONT_NAME, bold=FONT_NAME, italic=FONT_NAME, boldItalic=FONT_NAME,
)


def _gel(value) -> str:
    return f"₾{float(value or 0):,.2f}"


def _invoice_totals(total, vat_registered):
    amount = max(0.0, float(total or 0))
    vat = round(amount * 18 / 118, 2) if vat_registered else 0.0
    return round(amount - vat, 2), vat, amount


def _text(value, fallback="—") -> str:
    return escape(str(value or fallback))


def _styles():
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = FONT_NAME
    return styles


def _set_pdf_language(canvas, _doc):
    canvas._doc.Catalog.Lang = PDFString("ka-GE")


def _document(buffer, title):
    return SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=18 * mm, rightMargin=18 * mm, title=title, lang="ka-GE",
    )


def build_invoice_pdf(inv: dict) -> bytes:
    """Render the platform commission invoice in Georgian."""
    buf = BytesIO()
    doc = _document(buf, f"საკომისიოს ინვოისი №{inv.get('invoice_no', '')}")
    styles = _styles()
    title = ParagraphStyle("commissionTitle", parent=styles["Title"], textColor=TEAL, fontSize=19, spaceAfter=2)
    sub = ParagraphStyle("commissionSub", parent=styles["Normal"], textColor=GREY, fontSize=8, spaceAfter=0)
    label = ParagraphStyle("commissionLabel", parent=styles["Normal"], textColor=GREY, fontSize=8, spaceAfter=1)
    value = ParagraphStyle("commissionValue", parent=styles["Normal"], fontSize=9, leading=13)
    section = ParagraphStyle("commissionSection", parent=styles["Heading4"], textColor=TEAL, fontSize=10, spaceBefore=8, spaceAfter=4)
    right = ParagraphStyle("commissionRight", parent=value, alignment=2)
    elements = []

    heading = Table([[
        [Paragraph("Distro Logistics", title), Paragraph("საბითუმო დისტრიბუციის პლატფორმა", sub)],
        [
            Paragraph("საკომისიოს ინვოისი", ParagraphStyle("commissionRightTitle", parent=right, fontSize=12, textColor=TEAL)),
            Paragraph(f"№ {_text(inv.get('invoice_no'))}", right),
            Paragraph(f"პერიოდი: {_text(inv.get('period_label'))}", ParagraphStyle("commissionPeriod", parent=right, textColor=GREY)),
        ],
    ]], colWidths=[95 * mm, 79 * mm])
    heading.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.extend([heading, Spacer(1, 7 * mm)])

    issuer = [
        Paragraph("გამომწერი", label),
        Paragraph(_text(inv.get("issuer_name")), value),
        Paragraph(f"ს/კ: {_text(inv.get('issuer_tax_id'))}", value),
        Paragraph(f"IBAN: {_text(inv.get('issuer_iban'))}", value),
    ]
    supplier = [
        Paragraph("მიმღები / მომწოდებელი", label),
        Paragraph(_text(inv.get("supplier_name")), value),
        Paragraph(f"ს/კ: {_text(inv.get('supplier_tax_id'))}", value),
        Paragraph(_text(inv.get("supplier_email")), value),
    ]
    dates = [
        Paragraph("თარიღები", label),
        Paragraph(f"გამოწერის თარიღი: {_text(inv.get('issue_label'))}", value),
        Paragraph(f"გადახდის ვადა: {_text(inv.get('due_label'))}", value),
        Paragraph("გადახდის ვადა: 5 კალენდარული დღე", value),
    ]
    details = Table([[issuer, supplier, dates]], colWidths=[62 * mm, 62 * mm, 50 * mm])
    details.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    payment_reference = Paragraph(
        f"გადახდის დანიშნულება / reference: <b>{_text(inv.get('payment_reference'))}</b>", value,
    )
    elements.extend([details, Spacer(1, 3 * mm), payment_reference, Spacer(1, 5 * mm),
                     Paragraph("მიწოდებული შეკვეთები საანგარიშო პერიოდში", section)])

    rows = [["შეკვეთის №", "მიწოდების თარიღი", "შეკვეთის ჯამი", "საკომისიო"]]
    for item in inv.get("line_items", []):
        rows.append([
            _text(item.get("order_no")), _text(item.get("date")),
            _gel(item.get("order_total")), _gel(item.get("commission")),
        ])
    rows.append(["", "", "გადასახდელი ჯამი", _gel(inv.get("amount"))])
    table = Table(rows, colWidths=[48 * mm, 43 * mm, 42 * mm, 39 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, LIGHT]),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, colors.HexColor("#e5e7eb")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ecfdf5")),
        ("FONTNAME", (2, -1), (-1, -1), FONT_NAME),
        ("TEXTCOLOR", (3, -1), (3, -1), TEAL),
        ("FONTSIZE", (2, -1), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.extend([table, Spacer(1, 7 * mm), Paragraph("გადახდის პირობები", section)])
    terms = (
        f"საკომისიოს ინვოისი უნდა გადაიხადოთ გამოწერიდან 5 კალენდარული დღის განმავლობაში, "
        f"არაუგვიანეს {_text(inv.get('due_label'))}. ჩარიცხეთ {_gel(inv.get('amount'))} "
        f"გამომწერის ზემოთ მითითებულ საბანკო ანგარიშზე და დანიშნულებაში მიუთითეთ ინვოისის ნომერი "
        f"{_text(inv.get('invoice_no'))}. ვადაგადაცილებული დავალიანების დაფარვამდე ახალი შეკვეთების "
        "მიღება შესაძლოა დროებით შეიზღუდოს."
    )
    elements.append(Paragraph(terms, ParagraphStyle("commissionTerms", parent=value, textColor=GREY, leading=13)))
    elements.extend([
        Spacer(1, 8 * mm),
        Paragraph(
            "Distro Logistics · საკომისიოს ავტომატურად გენერირებული დოკუმენტი. "
            "ხელმოწერის გარეშე მოქმედია პლატფორმის საანგარიშო ჩანაწერად.",
            ParagraphStyle("commissionFooter", parent=sub, alignment=1),
        ),
    ])
    doc.build(elements, onFirstPage=_set_pdf_language, onLaterPages=_set_pdf_language)
    return buf.getvalue()


INVOICE_VALIDITY_NOTE = "ინვოისი ძალაშია 3 სამუშაო დღის განმავლობაში."
NO_DISCOUNT_NOTE = "* ფასდაკლება არ ეხება"
PAYMENT_TYPES = {
    "cash": "ნაღდი ანგარიშსწორება",
    "bank_transfer": "საბანკო გადარიცხვა",
    "consignment": "გადავადებული გადახდა",
    "online": "ონლაინ გადახდა",
    "card": "ბარათით გადახდა",
}


def _format_datetime(value) -> str:
    text = str(value or "")
    if not text:
        return "—"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(ZoneInfo("Asia/Tbilisi"))
        return parsed.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return text[:16]


def _bank_accounts(supplier: dict) -> list[dict]:
    accounts = [a for a in (supplier.get("bank_accounts") or []) if a.get("iban")]
    if not accounts and supplier.get("iban"):
        accounts = [{"bank_name": supplier.get("bank_name"), "iban": supplier.get("iban")}]
    return accounts


def _plain_number(value) -> str:
    return f"{float(value or 0):,.2f}"


def build_order_invoice_pdf(
    order: dict,
    supplier: dict | None = None,
    buyer: dict | None = None,
    due_date: str | None = None,
) -> bytes:
    """Render the Georgian B2B order invoice: header, buyer/supplier blocks, items, totals, validity."""
    supplier = supplier or {}
    buyer = buyer or {}
    vat_registered = bool(supplier.get("vat_registered"))
    products_total = round(max(0.0, float(order.get("total", 0) or 0)), 2)
    transport = round(max(0.0, float(order.get("delivery_fee") or order.get("transport_cost") or 0)), 2)
    _net, vat_amount, grand_total = _invoice_totals(products_total + transport, vat_registered)
    order_no = str(order.get("order_no") or order.get("id", ""))
    display_no = order_no if order_no.startswith("#") else f"#{order_no}"
    discount_percent = float(order.get("discount_percent") or 0)
    payment_type = PAYMENT_TYPES.get(str(order.get("payment_method") or "").lower(), "—")

    buf = BytesIO()
    doc = _document(buf, f"ინვოისი {display_no}")
    styles = _styles()
    title = ParagraphStyle("invTitle", parent=styles["Title"], textColor=TEAL, fontSize=16, leading=20, alignment=0, spaceAfter=2)
    stamp = ParagraphStyle("invStamp", parent=styles["Normal"], textColor=GREY, fontSize=8, leading=11)
    head = ParagraphStyle("invHead", parent=styles["Normal"], textColor=TEAL, fontSize=9, leading=12)
    value = ParagraphStyle("invValue", parent=styles["Normal"], fontSize=8, leading=11, wordWrap="CJK")
    muted = ParagraphStyle("invMuted", parent=styles["Normal"], textColor=GREY, fontSize=7, leading=10)
    right = ParagraphStyle("invRight", parent=value, alignment=2)

    def line(label_text, text):
        return Paragraph(f"<font color='#6b7280'>{escape(label_text)}:</font> {_text(text)}", value)

    elements = [
        Paragraph(f"ინვოისი {_text(display_no)}", title),
        Paragraph(f"თარიღი: {_format_datetime(order.get('created_at'))}", stamp),
        Spacer(1, 4 * mm),
    ]

    buyer_name = buyer.get("business_name") or order.get("retailer_name")
    legal_entity = buyer.get("legal_name") or buyer.get("business_name") or buyer.get("name") or order.get("retailer_name")
    buyer_tax_id = buyer.get("identification_number") or order.get("retailer_tax_id")
    buyer_cell = [
        Paragraph("დამკვეთი", head),
        line("მომხმარებლის ID", buyer.get("id") or order.get("retailer_id")),
        line("ფასდაკლება", f"{discount_percent:g}%"),
        line("დასახელება", buyer_name),
        line("ტელეფონი", order.get("customer_phone") or buyer.get("phone")),
        line("ელფოსტა", buyer.get("email")),
        line("მისამართი", order.get("delivery_address") or buyer.get("address")),
        line("იურიდიული პირი", legal_entity),
        line("საიდენტიფიკაციო კოდი", buyer_tax_id),
        line("ანგარიშსწორების ტიპი", payment_type),
        line("შენიშვნა", order.get("notes")),
        line("ტრანსპორტირების პირობები", order.get("delivery_window") or order.get("transport_terms")),
    ]

    supplier_cell = [
        Paragraph("მიმწოდებელი", head),
        line("კომპანია", supplier.get("business_name") or order.get("supplier_name")),
        line("საიდენტიფიკაციო კოდი", supplier.get("identification_number") or order.get("supplier_tax_id")),
        line("მისამართი", supplier.get("address")),
        line("ტელეფონი", supplier.get("phone")),
    ]
    accounts = _bank_accounts(supplier)
    supplier_cell.append(Paragraph("საბანკო რეკვიზიტები", head))
    if accounts:
        for account in accounts:
            code = account.get("bank_code") or str(account["iban"])[4:6]
            supplier_cell.append(Paragraph(
                f"<b>{_text(account.get('bank_name'))}</b> ({_text(code)})<br/>IBAN: {_text(account['iban'])}", value,
            ))
            supplier_cell.append(Spacer(1, 1.5 * mm))
    else:
        supplier_cell.append(Paragraph("—", value))

    parties = Table([[buyer_cell, supplier_cell]], colWidths=[87 * mm, 87 * mm])
    parties.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.extend([parties, Spacer(1, 5 * mm)])

    rows = [["#", "კოდი", "პროდუქტის დასახელება", "ფასი", "ფასდაკლება", "საბოლოო ფასი", "რაოდ.", "სულ (GEL)"]]
    has_exempt = False
    list_total = 0.0
    for index, item in enumerate(order.get("items", []), start=1):
        quantity = float(item.get("quantity", 0) or 0)
        unit_price = float(item.get("unit_price", 0) or 0)
        list_price = float(item.get("list_price") or unit_price)
        list_price = max(list_price, unit_price)
        exempt = bool(item.get("discount_exempt") or item.get("no_discount"))
        has_exempt = has_exempt or exempt
        name = _text(item.get("name")) + (" *" if exempt else "")
        discounted = list_price > unit_price
        list_total += list_price * quantity
        rows.append([
            str(index),
            Paragraph(_text(item.get("sku") or item.get("code")), value),
            Paragraph(name, value),
            Paragraph(f"<strike>{_plain_number(list_price)}</strike>", right) if discounted else _plain_number(list_price),
            f"-{(list_price - unit_price) / list_price * 100:.1f}%" if discounted else "—",
            _plain_number(unit_price),
            f"{quantity:g}",
            _plain_number(quantity * unit_price),
        ])
    if not order.get("items"):
        rows.append(["", "", Paragraph("საქონლის მონაცემები არ არის", value), "", "", "", "", ""])
    item_table = Table(rows, colWidths=[8 * mm, 22 * mm, 46 * mm, 22 * mm, 18 * mm, 22 * mm, 14 * mm, 22 * mm], repeatRows=1)
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#d1d5db")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(item_table)
    if has_exempt:
        elements.extend([Spacer(1, 2 * mm), Paragraph(NO_DISCOUNT_NOTE, muted)])

    savings = round(max(0.0, list_total - products_total), 2)
    summary_rows = []
    if savings > 0:
        summary_rows += [
            ["ფასდაკლებამდე ფასი", _gel(round(list_total, 2))],
            ["ფასდაკლება", "-" + _gel(savings)],
        ]
    summary_rows += [
        ["სულ პროდუქცია", _gel(products_total)],
        ["ტრანსპორტირების ღირებულება", _gel(transport)],
        ["საბოლოო ჯამი", _gel(grand_total)],
        ["მათ შორის დღგ (18%)" if vat_registered else "მათ შორის დღგ (არ არის დღგ-ს გადამხდელი)", _gel(vat_amount)],
    ]
    final_row = len(summary_rows) - 2
    summary = Table(summary_rows, colWidths=[85 * mm, 34 * mm], hAlign="RIGHT")
    summary.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, final_row), (-1, final_row), 0.8, TEAL),
        ("BACKGROUND", (0, final_row), (-1, final_row), LIGHT),
        ("TEXTCOLOR", (0, final_row), (-1, final_row), TEAL),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.extend([Spacer(1, 4 * mm), summary])
    if str(order.get("payment_method") or "").lower() == "bank_transfer" and order.get("payment_reference"):
        elements.extend([
            Spacer(1, 3 * mm),
            Paragraph(
                f"გადახდის დანიშნულებაში მიუთითეთ კოდი: <b>{_text(order.get('payment_reference'))}</b>",
                ParagraphStyle("invRef", parent=value, textColor=TEAL),
            ),
        ])
    elements.extend([
        Spacer(1, 10 * mm),
        Paragraph(INVOICE_VALIDITY_NOTE, ParagraphStyle("invValidity", parent=value, textColor=TEAL, fontSize=9)),
    ])
    doc.build(elements, onFirstPage=_set_pdf_language, onLaterPages=_set_pdf_language)
    return buf.getvalue()
