from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _esc(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_invoice_pdf(sale):
    """Return PDF bytes for a sale's invoice."""
    business, customer = sale.business, sale.customer
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Invoice {sale.invoice_number}")
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=2)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, leading=12)
    story = [Paragraph(_esc(business.name), h1)]
    biz_lines = [business.address, f"Phone: {business.phone}" if business.phone else "", f"GSTIN/Tax ID: {business.tax_id}" if business.tax_id else ""]
    story.append(Paragraph("<br/>".join(_esc(l) for l in biz_lines if l), small))
    story.append(Spacer(1, 8 * mm))

    status = sale.payment_status.upper()
    meta = [
        [Paragraph("<b>INVOICE</b>", styles["Heading2"]), ""],
        ["Invoice no.", sale.invoice_number],
        ["Date", timezone.localtime(sale.sale_date).strftime("%d %b %Y, %H:%M")],
        ["Payment status", status],
        ["Payment method", sale.get_payment_method_display()],
    ]
    t = Table(meta, colWidths=[40 * mm, 70 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story += [t, Spacer(1, 4 * mm)]

    story.append(Paragraph("<b>Billed to</b>", small))
    if customer:
        cust = "<br/>".join(_esc(x) for x in [customer.name, customer.phone, customer.email, customer.address] if x)
    else:
        cust = "Walk-in customer"
    story += [Paragraph(cust, small), Spacer(1, 6 * mm)]

    data = [["#", "Item", "Qty", "Price", "Discount", "Amount"]]
    for i, it in enumerate(sale.items.all(), 1):
        data.append([i, it.product_name, it.quantity, f"{it.unit_price:,.2f}", f"{it.discount:,.2f}", f"{it.line_total:,.2f}"])
    table = Table(data, colWidths=[10 * mm, 70 * mm, 15 * mm, 25 * mm, 25 * mm, 27 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f9")]),
    ]))
    story += [table, Spacer(1, 4 * mm)]

    cur = business.currency
    totals = [["Subtotal", f"{cur} {sale.subtotal:,.2f}"]]
    if sale.tax_amount:
        totals.append([f"Tax ({business.tax_rate}%)", f"{cur} {sale.tax_amount:,.2f}"])
    totals += [["Total", f"{cur} {sale.total:,.2f}"], ["Paid", f"{cur} {sale.amount_paid:,.2f}"], ["Balance due", f"{cur} {sale.balance:,.2f}"]]
    tt = Table(totals, colWidths=[40 * mm, 40 * mm], hAlign="RIGHT")
    tt.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 10), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                            ("FONTNAME", (0, 2 if sale.tax_amount else 1), (-1, 2 if sale.tax_amount else 1), "Helvetica-Bold")]))
    story += [tt, Spacer(1, 10 * mm), Paragraph("Thank you for your business.", small)]
    doc.build(story)
    return buf.getvalue()
