/* Facturation du back-office : formules et tarifs, encaissements, factures.
 *
 * Séparé d'admin.js pour la même raison que côté serveur : ouvrir des dates et
 * facturer un repas sont deux métiers, et celui-ci manipule de l'argent.
 *
 * Deux règles tiennent tout le fichier :
 *  - Les montants sont des entiers de centimes. La conversion en euros ne se
 *    fait qu'à l'affichage (`formatAmount`) et à la saisie (`parseAmount`).
 *  - Un brouillon en cours de saisie est capturé dans l'état AVANT tout
 *    re-rendu (`captureDraft`) : admin.js réécrit `innerHTML` en entier, et
 *    sans cette capture, ajouter une ligne effacerait les précédentes.
 */

import { request } from '../js/api.js';
import { escapeHtml, longDate, formatAmount, parseAmount, amountInput,
         SERVICE_LABEL, PAYMENT_KIND_LABEL, PAYMENT_METHOD_LABEL,
         BILLING_STATE_LABEL } from '../js/util.js';

export const api = {
  formulas: () => request('/api/admin/formulas'),
  createFormula: (body) => request('/api/admin/formulas', { method: 'POST', body: JSON.stringify(body) }),
  updateFormula: (id, body) => request(`/api/admin/formulas/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteFormula: (id) => request(`/api/admin/formulas/${id}`, { method: 'DELETE' }),
  invoices: () => request('/api/admin/invoices'),
  folder: (bookingId) => request(`/api/admin/bookings/${bookingId}/billing`),
  addPayment: (bookingId, body) => request(`/api/admin/bookings/${bookingId}/payments`, { method: 'POST', body: JSON.stringify(body) }),
  deletePayment: (id) => request(`/api/admin/payments/${id}`, { method: 'DELETE' }),
  createInvoice: (bookingId) => request(`/api/admin/bookings/${bookingId}/invoice`, { method: 'POST' }),
  updateInvoice: (id, body) => request(`/api/admin/invoices/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  issueInvoice: (id) => request(`/api/admin/invoices/${id}/issue`, { method: 'POST' }),
  cancelInvoice: (id, reason) => request(`/api/admin/invoices/${id}/cancel`, { method: 'POST', body: JSON.stringify({ reason }) }),
  sendInvoice: (id) => request(`/api/admin/invoices/${id}/send`, { method: 'POST' }),
  settings: () => request('/api/admin/settings'),
  saveSettings: (body) => request('/api/admin/settings', { method: 'PATCH', body: JSON.stringify(body) }),
};

/* Ce que le back-office montre du trajet, sur une carte comme dans un dossier.
   Trois états, tous nommés : une estimation connue, un échec avec son motif,
   ou rien encore demandé. Un blanc laisserait croire que la fonction manque. */
export function travelBadge(b, chefAddress) {
  const dest = [b.address, b.city].filter(Boolean).join(', ');
  const link = itinerary(chefAddress, dest, 'Trajet');
  if (b.travel_seconds) {
    const km = b.travel_meters ? ` · ${(b.travel_meters / 1000).toFixed(1)} km` : '';
    return `<span class="badge ok">${escapeHtml(formatDuration(b.travel_seconds))}${escapeHtml(km)}</span>${link}`;
  }
  if (b.travel_error) {
    return `<span class="badge warn" title="${escapeHtml(b.travel_error)}">trajet non estimé</span>${link}`;
  }
  if (!dest) return '';
  return `<button class="btn" data-travel="${b.id}">Estimer le trajet</button>${link}`;
}

/* Secondes -> « 34 min » / « 1 h 05 ». Même règle que côté serveur ; c'est le
   serveur qui fait foi, ceci sert aux valeurs fraîchement calculées. */
export function formatDuration(seconds) {
  if (!seconds) return '';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${String(m).padStart(2, '0')}` : `${h} h`;
}

export const billing = {
  formulas: [],
  pricingKinds: [],
  invoices: [],
  outstanding: 0,
  folder: null,        // {booking, data} — le dossier ouvert
  editingFormula: null, // id, ou 'new', ou null
  settings: { chef_address: '' },
};

/* Lien d'itinéraire vers l'application de cartes, pas un calcul embarqué : la
   page ne fait aucun appel réseau sortant, c'est le chef qui clique et c'est
   son téléphone qui ouvre la navigation. Le trajet est la seule chose qu'on ne
   sait pas donner sans dépendre d'un service tiers. */
export function itinerary(from, to, label = 'Itinéraire et durée') {
  if (!from || !to) return '';
  const url = `https://www.google.com/maps/dir/?api=1&origin=${encodeURIComponent(from)}`
    + `&destination=${encodeURIComponent(to)}&travelmode=driving`;
  return `<a class="btn" href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(label)}</a>`;
}

const stateBadge = (state) => {
  const klass = { paid: 'ok', partial: 'warn', unpaid: 'warn', overpaid: 'warn',
                  cancelled: 'neutral', unbilled: 'neutral' }[state] ?? 'neutral';
  return `<span class="badge ${klass}">${escapeHtml(BILLING_STATE_LABEL[state] ?? state)}</span>`;
};

// --- Formules -----------------------------------------------------------

function formulaForm(row) {
  const f = row ?? { name: '', description: '', pricing: 'per_guest', price_cents: 0,
                     min_guests: 0, active: 1, position: billing.formulas.length };
  const kinds = billing.pricingKinds.map((k) =>
    `<option value="${escapeHtml(k.value)}"${f.pricing === k.value ? ' selected' : ''}>${escapeHtml(k.label)}</option>`).join('');
  return `
    <form class="formula-form" data-formula-form="${row ? row.id : 'new'}">
      <div class="row">
        <label>Nom<input name="name" value="${escapeHtml(f.name)}" required maxlength="120" placeholder="Menu Signature"></label>
        <label>Tarification<select name="pricing">${kinds}</select></label>
      </div>
      <div class="row">
        <label>Prix en euros<input name="price" value="${escapeHtml(amountInput(f.price_cents))}" inputmode="decimal" placeholder="78,00"></label>
        <label>Convives minimum<input name="min_guests" type="number" min="0" max="500" value="${escapeHtml(f.min_guests)}"></label>
      </div>
      <label>Description<textarea name="description" rows="2" maxlength="600" placeholder="Cinq services, pain maison.">${escapeHtml(f.description)}</textarea></label>
      <div class="row">
        <label>Ordre d'affichage<input name="position" type="number" min="0" max="999" value="${escapeHtml(f.position)}"></label>
        <label class="check"><input name="active" type="checkbox"${f.active ? ' checked' : ''}> Visible sur le site</label>
      </div>
      <p class="hint">« Sur devis » ignore le prix : la formule s'affiche sans montant et la facture se chiffre à la main.</p>
      <div class="actions">
        <button class="btn primary" type="submit">${row ? 'Enregistrer' : 'Créer la formule'}</button>
        <button class="btn" type="button" data-formula-cancel="1">Annuler</button>
      </div>
    </form>`;
}

export function formulasPanel() {
  const rows = billing.formulas.map((f) => {
    if (billing.editingFormula === f.id) return `<div class="formula-row editing">${formulaForm(f)}</div>`;
    const off = f.active ? '' : ' <span class="badge neutral">retirée du site</span>';
    // Réglée « par convive » ou « forfait » mais sans montant : le site
    // l'affiche « sur devis ». Le dire, plutôt que de laisser le chef croire
    // qu'un tarif est posé — et plutôt que d'afficher « 0,00 € ».
    const noPrice = f.pricing !== 'quote' && f.price_cents <= 0
      ? ' <span class="badge warn">tarif non renseigné</span>' : '';
    // Une formule déjà choisie par un client ne propose pas « supprimer » :
    // le bouton n'existe pas plutôt que d'échouer une fois cliqué.
    const remove = f.in_use ? '' : `<button class="btn danger" data-formula-delete="${f.id}">Supprimer</button>`;
    return `
      <div class="formula-row">
        <div>
          <strong>${escapeHtml(f.name)}</strong>${off}${noPrice}
          <p class="meta">${escapeHtml(f.price_label)}${f.min_guests ? ` · dès ${escapeHtml(f.min_guests)} convives` : ''}</p>
          ${f.description ? `<p class="quote">${escapeHtml(f.description)}</p>` : ''}
        </div>
        <div class="actions">
          <button class="btn" data-formula-edit="${f.id}">Modifier</button>${remove}
        </div>
      </div>`;
  }).join('');

  return `
    <div class="panel">
      <h2>Formules et tarifs</h2>
      <p class="hint">Ce que voient vos clients sur le site, et ce qui sert de base à vos factures.
        Modifier un prix ici ne touche aucune facture déjà émise.</p>
      ${rows || '<p class="hint" style="margin:0">Aucune formule pour l\'instant : le site n\'affiche pas de section « Les formules ».</p>'}
      ${billing.editingFormula === 'new'
        ? `<div class="formula-row editing">${formulaForm(null)}</div>`
        : '<div class="actions" style="margin-top:1.25rem"><button class="btn primary" data-formula-new="1">Ajouter une formule</button></div>'}
    </div>`;
}

// --- Liste des factures --------------------------------------------------

export function invoicesPanel() {
  const rows = billing.invoices.map((i) => {
    const number = i.number ? escapeHtml(i.number) : 'brouillon';
    const balance = i.balance_cents === null || i.balance_cents === undefined ? ''
      : ` · solde ${escapeHtml(formatAmount(i.balance_cents))}`;
    const mail = i.status === 'issued' ? mailBadge(i) : '';
    return `
      <div class="invoice-row">
        <div>
          <strong>${number}</strong> · ${escapeHtml(i.name)}
          <p class="meta">${escapeHtml(longDate(i.date))} — ${escapeHtml(SERVICE_LABEL[i.service] ?? i.service)}
            · ${escapeHtml(formatAmount(i.total_cents))}${balance}</p>
        </div>
        <div class="actions">${stateBadge(i.state)}${mail}
          <button class="btn" data-folder-open="${i.booking_id}">Ouvrir le dossier</button></div>
      </div>`;
  }).join('');
  const head = billing.outstanding > 0
    ? `<p class="hint"><strong>${escapeHtml(formatAmount(billing.outstanding))}</strong> en attente de règlement.</p>`
    : '<p class="hint">Rien en attente de règlement.</p>';
  return `<div class="panel"><h2>Factures</h2>${head}
    ${rows || '<p class="hint" style="margin:0">Aucune facture pour l\'instant.</p>'}</div>`;
}

function mailBadge(invoice) {
  if (invoice.mail_status === 'sent') return '<span class="badge ok">envoyée au client</span>';
  if (invoice.mail_status === 'failed') {
    return `<span class="badge bad">envoi en échec</span> <span class="hint" style="margin:0">${escapeHtml(invoice.mail_error ?? '')}</span>`;
  }
  if (invoice.mail_status === 'disabled') return '<span class="badge warn">envoi désactivé</span>';
  return '<span class="badge neutral">pas encore envoyée</span>';
}

// --- Dossier d'une réservation ------------------------------------------

function draftEditor(invoice) {
  const lines = invoice.lines.map((l, index) => `
    <div class="line" data-line="${index}">
      <input name="label" value="${escapeHtml(l.label)}" maxlength="200" placeholder="Prestation">
      <input name="quantity" type="number" min="1" max="9999" value="${escapeHtml(l.quantity)}" aria-label="Quantité">
      <input name="unit" value="${escapeHtml(amountInput(l.unit_cents))}" inputmode="decimal" aria-label="Prix unitaire">
      <span class="num">${escapeHtml(formatAmount(l.quantity * l.unit_cents))}</span>
      <button class="btn danger" type="button" data-line-remove="${index}" aria-label="Retirer la ligne">×</button>
    </div>`).join('');
  const total = invoice.lines.reduce((n, l) => n + l.quantity * l.unit_cents, 0);
  return `
    <form class="draft" id="draft-form">
      <p class="hint">Brouillon : aucun numéro, rien n'est parti. Vous pouvez tout modifier.</p>
      <div class="lines">${lines}</div>
      <div class="actions"><button class="btn" type="button" data-line-add="1">Ajouter une ligne</button>
        <span class="draft-total">Total ${escapeHtml(formatAmount(total))}</span></div>
      <div class="row">
        <label>Échéance<input name="due_on" type="date" value="${escapeHtml(invoice.due_on ?? '')}"></label>
        <label>Mention libre<input name="notes" value="${escapeHtml(invoice.notes ?? '')}" maxlength="1000" placeholder="Merci de votre confiance."></label>
      </div>
      <div class="actions">
        <button class="btn" type="submit">Enregistrer le brouillon</button>
        <button class="btn primary" type="button" data-invoice-issue="${invoice.id}">Émettre la facture</button>
        <a class="btn" href="/api/admin/invoices/${invoice.id}/view" target="_blank" rel="noopener">Aperçu</a>
        <button class="btn danger" type="button" data-invoice-cancel="${invoice.id}">Jeter le brouillon</button>
      </div>
      <p class="hint">Émettre attribue le numéro et fige la facture : elle ne se modifiera plus.</p>
    </form>`;
}

function issuedInvoice(invoice) {
  const lines = invoice.lines.map((l) => `
    <div class="line frozen"><span>${escapeHtml(l.label)}</span><span class="num">${escapeHtml(l.quantity)}</span>
      <span class="num">${escapeHtml(formatAmount(l.unit_cents))}</span>
      <span class="num">${escapeHtml(formatAmount(l.quantity * l.unit_cents))}</span></div>`).join('');
  const vat = invoice.vat_rate_bp > 0
    ? `<p class="meta">HT ${escapeHtml(formatAmount(invoice.ht_cents))} · TVA ${escapeHtml(formatAmount(invoice.vat_cents))}</p>`
    : `<p class="meta">${escapeHtml(invoice.vat_note ?? '')}</p>`;
  return `
    <div class="issued">
      <p class="invoice-number">Facture <strong>${escapeHtml(invoice.number)}</strong>
        du ${escapeHtml(longDate(invoice.issued_on))} · ${escapeHtml(formatAmount(invoice.total_cents))}</p>
      <div class="lines">${lines}</div>
      ${vat}
      <div class="actions">
        ${mailBadge(invoice)}
        <a class="btn" href="/api/admin/invoices/${invoice.id}/view" target="_blank" rel="noopener">Voir / imprimer</a>
        <button class="btn primary" data-invoice-send="${invoice.id}">Envoyer au client</button>
        <button class="btn danger" data-invoice-cancel="${invoice.id}">Annuler la facture</button>
      </div>
      <p class="hint">Une facture émise ne se modifie plus. Pour corriger : annulez celle-ci — son numéro
        reste pris et son motif conservé — puis créez la suivante.</p>
    </div>`;
}

function paymentsBlock(booking, data) {
  const rows = data.payments.map((p) => `
    <div class="payment">
      <span>${escapeHtml(longDate(p.received_on))}</span>
      <span>${escapeHtml(PAYMENT_KIND_LABEL[p.kind] ?? p.kind)} · ${escapeHtml(PAYMENT_METHOD_LABEL[p.method] ?? p.method)}${p.note ? ` · ${escapeHtml(p.note)}` : ''}</span>
      <span class="num${p.amount_cents < 0 ? ' negative' : ''}">${escapeHtml(formatAmount(p.amount_cents))}</span>
      <button class="btn danger" data-payment-delete="${p.id}" aria-label="Supprimer cet encaissement">×</button>
    </div>`).join('');

  let balance;
  if (data.due_cents === null) {
    // Pas de facture émise : il n'y a pas de créance. On montre l'estimation
    // tirée de la formule, en disant que c'en est une.
    balance = data.estimate_cents !== null
      ? `<p class="meta">Reçu ${escapeHtml(formatAmount(data.paid_cents))} · estimation d'après la formule : ${escapeHtml(formatAmount(data.estimate_cents))} (pas encore facturé)</p>`
      : `<p class="meta">Reçu ${escapeHtml(formatAmount(data.paid_cents))} · montant à chiffrer à la main</p>`;
  } else {
    const rest = data.balance_cents;
    balance = `<p class="meta">Facturé ${escapeHtml(formatAmount(data.due_cents))} · reçu ${escapeHtml(formatAmount(data.paid_cents))} · ${
      rest > 0 ? `<strong>reste ${escapeHtml(formatAmount(rest))}</strong>`
      : rest === 0 ? 'soldé' : `<strong>trop-perçu ${escapeHtml(formatAmount(-rest))}</strong>`}</p>`;
  }

  const methods = Object.entries(PAYMENT_METHOD_LABEL).map(([v, l]) =>
    `<option value="${escapeHtml(v)}">${escapeHtml(l)}</option>`).join('');
  const kinds = Object.entries(PAYMENT_KIND_LABEL).map(([v, l]) =>
    `<option value="${escapeHtml(v)}">${escapeHtml(l)}</option>`).join('');

  return `
    <section class="folder-section">
      <h3>Encaissements</h3>
      ${rows || '<p class="hint" style="margin:0 0 .75rem">Rien de reçu pour l\'instant.</p>'}
      ${balance}
      <form class="payment-form" id="payment-form" data-booking="${booking.id}">
        <input name="amount" inputmode="decimal" placeholder="Montant en euros" required aria-label="Montant">
        <select name="kind" aria-label="Type">${kinds}</select>
        <select name="method" aria-label="Moyen">${methods}</select>
        <input name="received_on" type="date" aria-label="Date de réception">
        <input name="note" maxlength="300" placeholder="Note (facultatif)" aria-label="Note">
        <button class="btn primary" type="submit">Enregistrer</button>
      </form>
      <p class="hint">Un remboursement se saisit en positif : le type suffit à le retrancher du solde.</p>
    </section>`;
}

/* Dire pourquoi le lien manque plutôt que de ne rien afficher : sans cela, un
   chef qui n'a pas renseigné son adresse de départ croit la fonction absente. */
function travelLine(booking, data) {
  const from = data.chef_address;
  const to = data.client_address || booking.address;
  if (!to) return '<p class="travel muted">Aucune adresse de repas : le client ne l\'a pas renseignée.</p>';
  if (!from) {
    return `<p class="travel muted">${escapeHtml(to)} — renseigne ton adresse de départ dans Réglages pour estimer le trajet.</p>`;
  }
  const t = data.travel ?? {};
  const link = itinerary(from, to);
  let state;
  if (t.seconds) {
    // « estimation » et pas « durée » : c'est une conduite sans trafic, pas
    // une promesse d'heure d'arrivée. L'adresse reconnue est montrée avec :
    // sans elle, une localisation de travers passe inaperçue.
    const seen = t.label_seen
      ? `<span class="hint" style="margin:0">localisé : ${escapeHtml(t.label_seen)}</span>` : '';
    state = `<span class="badge ok">${escapeHtml(t.label)}${t.km ? escapeHtml(` · ${t.km} km`) : ''}</span>
             <span class="hint" style="margin:0">estimation en voiture, sans trafic</span>${seen}`;
  } else if (t.error) {
    state = `<span class="badge warn">trajet non estimé</span>
             <span class="hint" style="margin:0">${escapeHtml(t.error)}</span>`;
  } else {
    state = '';
  }
  const action = `<button class="btn" data-travel="${booking.id}">${t.seconds || t.error ? 'Recalculer' : 'Estimer le trajet'}</button>`;
  return `<p class="travel">${escapeHtml(to)} ${state} ${action} ${link}</p>`;
}

export function settingsPanel() {
  const s = billing.settings;
  return `
    <div class="panel">
      <h2>Réglages</h2>
      <p class="hint">Ce qui vous concerne, et que le site public ne montre jamais.</p>
      <form class="formula-form" id="settings-form">
        <label>Votre adresse de départ
          <input name="chef_address" value="${escapeHtml(s.chef_address ?? '')}" maxlength="300"
                 placeholder="12 rue des Olivettes, 44000 Nantes" autocomplete="street-address">
        </label>
        <p class="hint" style="margin:0 0 1rem">D'où vous partez pour aller cuisiner. Elle sert à
          calculer le trajet jusqu'à chaque client, depuis la fiche de la réservation. Elle reste
          dans votre back-office : elle n'apparaît ni sur le site, ni sur vos factures, et n'est
          jamais communiquée à un client.</p>
        <div class="actions"><button class="btn primary" type="submit">Enregistrer</button></div>
      </form>
    </div>`;
}

export function folderPanel() {
  const { booking, data } = billing.folder;
  const invoice = data.invoice;

  let invoiceBlock;
  if (!invoice) {
    const hint = data.estimate_cents !== null
      ? `Le brouillon partira de la formule : ${escapeHtml(formatAmount(data.estimate_cents))}.`
      : 'Aucun tarif automatique pour cette formule : le brouillon partira à zéro, à chiffrer.';
    invoiceBlock = `<p class="hint">${hint}</p>
      <button class="btn primary" data-invoice-create="${booking.id}">Créer un brouillon de facture</button>`;
  } else if (invoice.editable) {
    invoiceBlock = draftEditor(invoice);
  } else {
    invoiceBlock = issuedInvoice(invoice);
  }

  return `
    <div class="panel folder">
      <div class="folder-head">
        <div>
          <h2>${escapeHtml(booking.name)}</h2>
          <p class="hint">${escapeHtml(longDate(booking.date))} — ${escapeHtml(SERVICE_LABEL[booking.service] ?? booking.service)}
            · ${escapeHtml(booking.guests)} couverts · ${escapeHtml(booking.formula || 'formule à définir')} · réf. ${escapeHtml(booking.ref)}</p>
          ${travelLine(booking, data)}
        </div>
        <button class="btn" data-folder-close="1">Fermer</button>
      </div>
      <section class="folder-section"><h3>Facture</h3>${invoiceBlock}</section>
      ${paymentsBlock(booking, data)}
    </div>`;
}

// --- Capture avant re-rendu ---------------------------------------------

/* admin.js réécrit tout le DOM à chaque rendu. Les champs du brouillon sont
 * donc relus dans l'état avant chaque re-rendu déclenché depuis l'éditeur --
 * sans quoi ajouter une ligne effacerait ce qui vient d'être tapé. */
export function captureDraft() {
  const form = document.getElementById('draft-form');
  const invoice = billing.folder?.data?.invoice;
  if (!form || !invoice) return;
  invoice.lines = [...form.querySelectorAll('.line')].map((el) => ({
    label: el.querySelector('[name=label]').value,
    quantity: Math.max(1, Number(el.querySelector('[name=quantity]').value) || 1),
    unit_cents: parseAmount(el.querySelector('[name=unit]').value) ?? 0,
  }));
  invoice.due_on = form.elements.due_on.value;
  invoice.notes = form.elements.notes.value;
}

export function draftPayload() {
  const invoice = billing.folder.data.invoice;
  return {
    lines: invoice.lines.map((l) => ({
      label: l.label.trim() || 'Prestation',
      quantity: l.quantity,
      unit: amountInput(l.unit_cents),
    })),
    notes: invoice.notes ?? '',
    due_on: invoice.due_on ?? '',
    vat_rate_bp: invoice.vat_rate_bp ?? 0,
  };
}
