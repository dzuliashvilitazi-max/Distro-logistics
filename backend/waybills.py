from datetime import datetime
from html import escape


def _text(value) -> str:
    return escape(str(value or "—"))


def _amount(value) -> str:
    return f"₾{float(value or 0):,.2f}"


def build_waybill_html(document: dict) -> str:
    seller = document["seller"]
    buyer = document["buyer"]
    dispatch = document["dispatch"]
    item_rows = "".join(
        "<tr>"
        f"<td>{_text(item.get('name'))}</td>"
        f"<td>{_text(item.get('quantity'))}</td>"
        f"<td>{_text(item.get('unit', 'ერთეული'))}</td>"
        f"<td>{_amount(item.get('unit_price'))}</td>"
        f"<td>{_amount(item.get('line_total'))}</td>"
        "</tr>"
        for item in document["items"]
    )
    return f'''<!doctype html>
<html lang="ka">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ზედნადები { _text(document.get("waybill_no")) }</title>
  <style>
    @page {{ size: A4; margin: 16mm; }}
    * {{ box-sizing: border-box; }}
    body {{ color: #17212b; font: 14px/1.5 Arial, sans-serif; margin: 0 auto; max-width: 190mm; }}
    header {{ border-bottom: 2px solid #166b5b; margin-bottom: 20px; padding-bottom: 14px; }}
    h1 {{ color: #14594d; font-size: 23px; margin: 0; }}
    .draft {{ color: #8a3b16; font-size: 12px; font-weight: bold; margin-top: 5px; }}
    .meta, .parties {{ display: grid; gap: 12px; grid-template-columns: 1fr 1fr; margin: 16px 0; }}
    .box {{ border: 1px solid #cbd5d1; padding: 12px; }}
    .label {{ color: #52625d; font-size: 11px; font-weight: bold; text-transform: uppercase; }}
    .value {{ overflow-wrap: anywhere; }}
    table {{ border-collapse: collapse; margin-top: 18px; width: 100%; }}
    th {{ background: #e7f2ef; text-align: left; }}
    td, th {{ border: 1px solid #cbd5d1; padding: 7px; }}
    td:nth-child(n+2), th:nth-child(n+2) {{ text-align: right; }}
    tfoot td {{ font-weight: bold; }}
    .notice {{ background: #fff7ed; border: 1px solid #fed7aa; margin-top: 20px; padding: 10px; }}
    .signatures {{ display: grid; gap: 28px; grid-template-columns: 1fr 1fr; margin-top: 52px; }}
    .signature {{ border-top: 1px solid #52625d; padding-top: 6px; }}
    @media print {{ body {{ max-width: none; }} }}
  </style>
</head>
<body>
  <header>
    <h1>სასაქონლო ზედნადები</h1>
    <div class="draft">საბეჭდი პროექტი · არ არის შემოსავლების სამსახურში რეგისტრირებული ოფიციალური ზედნადები</div>
  </header>
  <section class="meta">
    <div class="box"><div class="label">დოკუმენტის ნომერი</div><div class="value">{_text(document.get("waybill_no"))}</div></div>
    <div class="box"><div class="label">შედგენის თარიღი</div><div class="value">{_text(document.get("issued_at"))}</div></div>
    <div class="box"><div class="label">შეკვეთის ნომერი</div><div class="value">{_text(document.get("order_no"))}</div></div>
    <div class="box"><div class="label">მიწოდების მისამართი</div><div class="value">{_text(document.get("delivery_address"))}</div></div>
  </section>
  <section class="parties">
    <div class="box">
      <div class="label">გამყიდველი / გამგზავნი</div>
      <div class="value"><strong>{_text(seller.get("name"))}</strong></div>
      <div class="value">საიდენტიფიკაციო კოდი: {_text(seller.get("tax_id"))}</div>
      <div class="value">მისამართი: {_text(seller.get("address"))}</div>
      <div class="value">ტელეფონი: {_text(seller.get("phone"))}</div>
    </div>
    <div class="box">
      <div class="label">მყიდველი / მიმღები</div>
      <div class="value"><strong>{_text(buyer.get("name"))}</strong></div>
      <div class="value">საიდენტიფიკაციო კოდი: {_text(buyer.get("tax_id"))}</div>
      <div class="value">მისამართი: {_text(buyer.get("address"))}</div>
      <div class="value">ტელეფონი: {_text(buyer.get("phone"))}</div>
    </div>
  </section>
  <section class="parties">
    <div class="box"><div class="label">მძღოლი</div><div class="value">{_text(dispatch.get("driver_name"))}</div>
      <div class="value">პირადი ნომერი: {_text(dispatch.get("driver_id"))}</div></div>
    <div class="box"><div class="label">ტრანსპორტი</div><div class="value">სახეობა: {_text(dispatch.get("transport_type"))}</div>
      <div class="value">სახელმწიფო ნომერი: {_text(dispatch.get("vehicle_plate"))}</div></div>
  </section>
  <table>
    <thead><tr><th>საქონლის დასახელება</th><th>რაოდენობა</th><th>ერთეული</th><th>ერთეულის ფასი</th><th>ჯამი</th></tr></thead>
    <tbody>{item_rows}</tbody>
    <tfoot><tr><td colspan="4">სულ</td><td>{_amount(document.get("total"))}</td></tr></tfoot>
  </table>
  <div class="notice">ეს დოკუმენტი მომზადებულია შეკვეთის მონაცემებზე დაყრდნობით, როგორც შიდა საბეჭდი ფორმა. იგი არ ანაცვლებს საქართველოს შემოსავლების სამსახურის ოფიციალურ ელექტრონულ ზედნადებს და არ ადასტურებს მის რეგისტრაციას.</div>
  <div class="signatures"><div class="signature">გამგზავნის ხელმოწერა</div><div class="signature">მიმღების ხელმოწერა</div></div>
</body>
</html>'''