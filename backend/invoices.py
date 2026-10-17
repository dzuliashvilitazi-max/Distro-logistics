"""Official commission invoice PDF generation (reportlab)."""
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)

TEAL = colors.HexColor("#0f766e")
LIGHT = colors.HexColor("#f0fdfa")
GREY = colors.HexColor("#6b7280")


def _gel(v) -> str:
    return f"GEL {float(v):,.2f}"


def build_invoice_pdf(inv: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                            leftMargin=18 * mm, rightMargin=18 * mm, title=inv.get("invoice_no", "Invoice"))
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Title"], textColor=TEAL, fontSize=22, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=styles["Normal"], textColor=GREY, fontSize=9, spaceAfter=0)
    lab = ParagraphStyle("lab", parent=styles["Normal"], textColor=GREY, fontSize=8, spaceAfter=1)
    val = ParagraphStyle("val", parent=styles["Normal"], fontSize=10, leading=14)
    sec = ParagraphStyle("sec", parent=styles["Heading4"], textColor=TEAL, fontSize=11, spaceBefore=10, spaceAfter=4)
    e = []

    title_tbl = Table([[
        [Paragraph("Distro Logistics", h), Paragraph("B2B Distribution Platform", sub)],
        [Paragraph("COMMISSION INVOICE", ParagraphStyle("r", parent=styles["Normal"], alignment=2, fontSize=13,
                                                        textColor=TEAL, fontName="Helvetica-Bold")),
         Paragraph(f'No. {inv.get("invoice_no","")}', ParagraphStyle("r2", parent=styles["Normal"], alignment=2, fontSize=10)),
         Paragraph(f'Period: {inv.get("period_label","")}', ParagraphStyle("r3", parent=styles["Normal"], alignment=2, fontSize=9, textColor=GREY))],
    ]], colWidths=[95 * mm, 79 * mm])
    title_tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    e.append(title_tbl)
    e.append(Spacer(1, 8 * mm))

    issuer = [Paragraph("FROM (Issuer)", lab),
              Paragraph(inv.get("issuer_name", ""), val),
              Paragraph(f'Tax ID: {inv.get("issuer_tax_id","")}', val),
              Paragraph(f'IBAN: {inv.get("issuer_iban","")}', val)]
    billto = [Paragraph("BILL TO (Supplier)", lab),
              Paragraph(inv.get("supplier_name", ""), val),
              Paragraph(f'Tax ID: {inv.get("supplier_tax_id","") or "—"}', val),
              Paragraph(inv.get("supplier_email", ""), val)]
    meta = [Paragraph("DATES", lab),
            Paragraph(f'Issued: {inv.get("issue_label","")}', val),
            Paragraph(f'Due: {inv.get("due_label","")}', ParagraphStyle("due", parent=val, textColor=colors.HexColor("#b91c1c"), fontName="Helvetica-Bold")),
            Paragraph("Term: 5 calendar days", val)]
    info = Table([[issuer, billto, meta]], colWidths=[62 * mm, 62 * mm, 50 * mm])
    info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    e.append(info)
    e.append(Spacer(1, 6 * mm))

    e.append(Paragraph("Delivered orders in billing period", sec))
    data = [["Order No.", "Delivered", "Order Total", "Commission"]]
    for li in inv.get("line_items", []):
        data.append([li.get("order_no", ""), li.get("date", ""), _gel(li.get("order_total", 0)), _gel(li.get("commission", 0))])
    data.append(["", "", "TOTAL DUE", _gel(inv.get("amount", 0))])
    tbl = Table(data, colWidths=[52 * mm, 42 * mm, 40 * mm, 40 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, LIGHT]),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, colors.HexColor("#e5e7eb")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ecfdf5")),
        ("FONTNAME", (2, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (3, -1), (3, -1), TEAL),
        ("FONTSIZE", (2, -1), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    e.append(tbl)
    e.append(Spacer(1, 8 * mm))

    terms = (f'Payment terms: This commission invoice is payable within 5 (five) calendar days of issuance, '
             f'i.e. on or before {inv.get("due_label","")}. Please remit the total amount of {_gel(inv.get("amount",0))} '
             f'via bank transfer to the issuer IBAN stated above, quoting invoice number {inv.get("invoice_no","")}. '
             f'Overdue invoices result in a temporary suspension of new order acceptance until payment is reconciled.')
    e.append(Paragraph("Terms", sec))
    e.append(Paragraph(terms, ParagraphStyle("t", parent=styles["Normal"], fontSize=9, textColor=GREY, leading=13)))
    e.append(Spacer(1, 10 * mm))
    e.append(Paragraph("Distro Logistics — automated commission billing. Generated electronically; valid without signature.",
                       ParagraphStyle("f", parent=styles["Normal"], fontSize=8, textColor=GREY, alignment=1)))

    doc.build(e)
    buf.seek(0)
    return buf.getvalue()
