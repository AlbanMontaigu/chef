"""Rendu d'une facture en HTML imprimable.

Pas de bibliothèque PDF : la contrainte de dépendances minimales du dépôt
tient toujours, et le navigateur sait imprimer en PDF. La page porte donc son
propre style d'impression et n'a besoin de rien d'extérieur -- c'est aussi ce
qui la rend attachable telle quelle à un e-mail.

Tout ce qui vient d'un client ou du chef passe par `escape()` : un nom
d'entreprise avec une esperluette, une adresse avec un chevron, un libellé de
ligne libre -- aucun n'a le droit d'être interpolé brut.
"""

from datetime import date
from html import escape

from . import money

_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]

STYLE = """
  :root { --ink:#241c17; --muted:#6d635b; --line:#e0d7cc; --accent:#8a5a3b; }
  * { box-sizing: border-box; }
  body { margin:0; padding:2.5rem 1.5rem; color:var(--ink); background:#f6f1ea;
         font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  .sheet { max-width:52rem; margin:0 auto; background:#fff; padding:3rem;
           border:1px solid var(--line); border-radius:6px; }
  header { display:flex; justify-content:space-between; gap:2rem; flex-wrap:wrap;
           border-bottom:2px solid var(--accent); padding-bottom:1.5rem; }
  h1 { font-size:1.6rem; margin:0 0 .35rem; letter-spacing:.02em; }
  .who { font-size:.92rem; color:var(--muted); white-space:pre-line; }
  .who strong { color:var(--ink); font-size:1rem; display:block; margin-bottom:.2rem; }
  .meta { text-align:right; font-size:.92rem; }
  .meta b { display:block; font-size:1.25rem; color:var(--accent); }
  .parties { display:flex; justify-content:space-between; gap:2rem; flex-wrap:wrap;
             margin:2rem 0 1.5rem; }
  .label { text-transform:uppercase; letter-spacing:.08em; font-size:.72rem;
           color:var(--muted); margin-bottom:.4rem; }
  table { width:100%; border-collapse:collapse; margin-top:1rem; }
  th { text-align:left; font-size:.72rem; text-transform:uppercase; letter-spacing:.08em;
       color:var(--muted); border-bottom:1px solid var(--line); padding:.5rem .4rem; }
  td { padding:.7rem .4rem; border-bottom:1px solid var(--line); vertical-align:top; }
  .num { text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }
  tfoot td { border:none; padding:.35rem .4rem; }
  tfoot .total td { font-size:1.15rem; font-weight:700; border-top:2px solid var(--accent);
                    padding-top:.7rem; }
  .balance { margin-top:1.5rem; padding:1rem 1.2rem; background:#faf5ee;
             border:1px solid var(--line); border-radius:4px; font-size:.95rem; }
  .balance .due { font-weight:700; color:var(--accent); }
  .notes, .terms { margin-top:1.5rem; font-size:.9rem; color:var(--muted); white-space:pre-line; }
  .draft { margin-bottom:1.5rem; padding:.8rem 1rem; border:1px dashed var(--accent);
           border-radius:4px; color:var(--accent); font-weight:600; }
  .cancelled { margin-bottom:1.5rem; padding:.8rem 1rem; background:#fdecea;
               border:1px solid #e5b4ae; border-radius:4px; color:#8c2f21; font-weight:600; }
  @media print {
    body { background:#fff; padding:0; }
    .sheet { border:none; padding:0; max-width:none; }
    .no-print { display:none; }
  }
"""


def _fr_date(iso: str | None) -> str:
    if not iso:
        return "—"
    d = date.fromisoformat(iso)
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def _block(lines: list[str]) -> str:
    return "<br>".join(escape(line) for line in lines if line)


def render(invoice: dict, payments: list[dict], *, standalone: bool = True) -> str:
    seller, client = invoice["seller"], invoice["client"]
    total = invoice["total_cents"]
    paid = sum(int(p["amount_cents"]) for p in payments)
    balance = total - paid

    banner = ""
    if invoice["status"] == "draft":
        banner = ('<p class="draft">Brouillon — cette facture n\'a pas encore été émise. '
                  'Elle ne porte pas de numéro et ne fait pas foi.</p>')
    elif invoice["status"] == "cancelled":
        reason = invoice.get("cancel_reason") or ""
        banner = ('<p class="cancelled">Facture annulée'
                  + (f" — {escape(reason)}" if reason else "")
                  + "</p>")

    rows = "".join(
        f"<tr><td>{escape(line['label'])}</td>"
        f"<td class='num'>{int(line['quantity'])}</td>"
        f"<td class='num'>{escape(money.format_amount(int(line['unit_cents'])))}</td>"
        f"<td class='num'>{escape(money.format_amount(int(line['quantity']) * int(line['unit_cents'])))}</td></tr>"
        for line in invoice["lines"]
    )

    if invoice["vat_rate_bp"] > 0:
        totals = (
            f"<tr><td colspan='3' class='num'>Total HT</td>"
            f"<td class='num'>{escape(money.format_amount(invoice['ht_cents']))}</td></tr>"
            f"<tr><td colspan='3' class='num'>TVA {escape(money.format_rate(invoice['vat_rate_bp']))}</td>"
            f"<td class='num'>{escape(money.format_amount(invoice['vat_cents']))}</td></tr>"
            f"<tr class='total'><td colspan='3' class='num'>Total TTC</td>"
            f"<td class='num'>{escape(money.format_amount(total))}</td></tr>"
        )
    else:
        totals = (
            f"<tr class='total'><td colspan='3' class='num'>Total</td>"
            f"<td class='num'>{escape(money.format_amount(total))}</td></tr>"
        )

    received = ""
    if payments:
        items = "".join(
            f"<div>{escape(_fr_date(p['received_on']))} — "
            f"{escape(money.format_amount(int(p['amount_cents'])))} "
            f"({escape(p['method'])}{', ' + escape(p['note']) if p['note'] else ''})</div>"
            for p in payments
        )
        state = ("Solde : <span class='due'>" + escape(money.format_amount(balance)) + "</span>"
                 if balance > 0 else
                 "Facture soldée." if balance == 0 else
                 "Trop-perçu : <span class='due'>" + escape(money.format_amount(-balance)) + "</span>")
        received = f"<div class='balance'><div class='label'>Encaissements</div>{items}<p>{state}</p></div>"

    terms = []
    if invoice["vat_rate_bp"] <= 0 and invoice["vat_note"]:
        terms.append(invoice["vat_note"])
    if seller.get("payment_terms"):
        terms.append(seller["payment_terms"])
    if seller.get("iban"):
        terms.append(f"IBAN {seller['iban']}" + (f" — BIC {seller['bic']}" if seller.get("bic") else ""))
    if invoice.get("due_on"):
        terms.append(f"Échéance : {_fr_date(invoice['due_on'])}")

    body = f"""
  <div class="sheet">
    {banner}
    <header>
      <div class="who"><strong>{escape(seller.get('name') or '')}</strong>{_block([
        seller.get('address', ''), seller.get('status', ''),
        f"SIRET {seller['siret']}" if seller.get('siret') else '',
        seller.get('email', ''), seller.get('phone', '')])}</div>
      <div class="meta">
        <span class="label">Facture</span>
        <b>{escape(invoice['number'] or 'brouillon')}</b>
        <div>Émise le {escape(_fr_date(invoice.get('issued_on')))}</div>
      </div>
    </header>
    <div class="parties">
      <div><div class="label">Facturé à</div>
        <div class="who">{_block([client.get('name', ''), client.get('address', ''),
                                  client.get('email', ''), client.get('phone', '')])}</div></div>
    </div>
    <table>
      <thead><tr><th>Prestation</th><th class="num">Qté</th><th class="num">P.U.</th><th class="num">Montant</th></tr></thead>
      <tbody>{rows}</tbody>
      <tfoot>{totals}</tfoot>
    </table>
    {received}
    {f'<p class="notes">{escape(invoice["notes"])}</p>' if invoice.get('notes') else ''}
    {f'<p class="terms">{_block(terms)}</p>' if terms else ''}
  </div>"""

    if not standalone:
        return body
    title = f"Facture {invoice['number']}" if invoice["number"] else "Facture (brouillon)"
    return (f"<!DOCTYPE html>\n<html lang=\"fr\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<meta name=\"robots\" content=\"noindex, nofollow\">"
            f"<title>{escape(title)}</title><style>{STYLE}</style></head>"
            f"<body>{body}</body></html>")


def text_summary(invoice: dict, site_name: str) -> str:
    """Corps texte de l'e-mail. La facture est jointe en HTML, mais un client
    qui lit ses messages sans ouvrir les pièces jointes doit tout de même
    savoir combien il doit, à qui et pour quand."""
    lines = [f"  {l['label']} : {money.format_amount(int(l['quantity']) * int(l['unit_cents']))}"
             for l in invoice["lines"]]
    seller = invoice["seller"]
    tail = []
    if seller.get("iban"):
        tail.append(f"IBAN : {seller['iban']}")
    if invoice.get("due_on"):
        tail.append(f"Échéance : {_fr_date(invoice['due_on'])}")
    if invoice["vat_rate_bp"] <= 0 and invoice["vat_note"]:
        tail.append(invoice["vat_note"])
    return (
        f"Bonjour {invoice['client'].get('name', '')},\n\n"
        f"Voici la facture {invoice['number']} du {_fr_date(invoice.get('issued_on'))}.\n\n"
        + "\n".join(lines)
        + f"\n\n  Total : {money.format_amount(invoice['total_cents'])}\n\n"
        + ("\n".join(tail) + "\n\n" if tail else "")
        + f"La facture complète est jointe à ce message.\n\n"
        f"Merci de votre confiance,\n{site_name}\n"
    )
