import { request } from '../js/api.js';
import { escapeHtml, longDate, monthLabel, isoOf, daysInMonth, weekdayIndex,
         todayISO, formatAmount, parseAmount, SERVICE_LABEL,
         BILLING_STATE_LABEL, dietBadges } from '../js/util.js';
import { api as billingApi, billing, formulasPanel, invoicesPanel, folderPanel,
         settingsPanel, remindersPanel, quotesPanel, travelBadge, captureDraft,
         draftPayload } from './billing.js';

const app = document.getElementById('app');
const WEEKDAYS = ['L', 'M', 'M', 'J', 'V', 'S', 'D'];
const SERVICES = ['midi', 'soir'];

const TABS = [
  ['agenda', 'Agenda'],
  ['facturation', 'Facturation'],
  ['formules', 'Formules'],
  ['devis', 'Devis'],
  ['relances', 'Relances'],
  ['reglages', 'Réglages'],
];

const view = {
  tab: 'agenda',
  authenticated: false,
  configured: true,
  mailEnabled: true,
  month: null,
  slots: [],
  bookings: [],
  firstBookable: null,
  picked: new Set(),   // dates cochées dans le calendrier
  error: '',
  flash: '',
  busy: false,
};

const api = {
  session: () => request('/api/admin/session'),
  login: (password) => request('/api/admin/login', { method: 'POST', body: JSON.stringify({ password }) }),
  logout: () => request('/api/admin/logout', { method: 'POST' }),
  slots: (start, end) => request(`/api/admin/slots?start=${start}&end=${end}`),
  openSlots: (items) => request('/api/admin/slots', { method: 'POST', body: JSON.stringify({ items }) }),
  closeSlot: (id) => request(`/api/admin/slots/${id}`, { method: 'DELETE' }),
  bookings: () => request('/api/admin/bookings?status=confirmed'),
  cancel: (id, reason) => request(`/api/admin/bookings/${id}/cancel`, { method: 'POST', body: JSON.stringify({ reason }) }),
  resend: (id) => request(`/api/admin/bookings/${id}/resend`, { method: 'POST' }),
  travel: (id) => request(`/api/admin/bookings/${id}/travel`, { method: 'POST' }),
  ...billingApi,
};

const monthBounds = () => {
  const { year, month } = view.month;
  return [isoOf(year, month, 1), isoOf(year, month, daysInMonth(year, month))];
};
const slotAt = (date, service) => view.slots.find((s) => s.date === date && s.service === service) ?? null;

// --- Vues ---------------------------------------------------------------

function loginView() {
  const warning = view.configured ? '' :
    `<p class="error">ADMIN_PASSWORD n'est pas configuré côté serveur : le back-office reste inutilisable tant que la variable n'est pas posée dans Coolify.</p>`;
  return `
    <div class="wrap">
      <form class="panel admin-login" id="login-form">
        <h1>Votre back-office</h1>
        <p class="hint">Ouvrez vos dates, suivez vos réservations.</p>
        ${warning}
        <label>Mot de passe<input name="password" type="password" autocomplete="current-password" required></label>
        ${view.error ? `<p class="error" role="alert" style="margin-top:0.75rem">${escapeHtml(view.error)}</p>` : ''}
        <button class="cta" type="submit" style="margin-top:1.25rem;width:100%" ${view.busy ? 'disabled' : ''}>Entrer</button>
      </form>
    </div>`;
}

function summary() {
  const today = todayISO();
  const upcoming = view.bookings.filter((b) => b.date >= today);
  const covers = upcoming.reduce((n, b) => n + b.guests, 0);
  const openFree = view.slots.filter((s) => !s.booking_id && s.date >= today).length;
  const issues = view.bookings.filter((b) =>
    [b.mail_client, b.mail_chef].some((s) => s === 'failed' || s === 'disabled')).length;
  // Un repas déjà servi et non facturé est de l'argent oublié, pas une tâche
  // en cours : il ne compte qu'une fois la date passée.
  const toBill = view.bookings.filter((b) => b.date < today && !b.invoice_id).length;
  const allergies = upcoming.filter((b) => (b.diets_detail ?? []).some((d) => d.allergy)).length;
  const cards = [
    `<div class="stat"><b>${upcoming.length}</b><s>réservation${upcoming.length > 1 ? 's' : ''} à venir</s></div>`,
    `<div class="stat"><b>${covers}</b><s>couverts à préparer</s></div>`,
    `<div class="stat"><b>${openFree}</b><s>créneau${openFree > 1 ? 'x' : ''} libre${openFree > 1 ? 's' : ''} ce mois</s></div>`,
    issues ? `<div class="stat alert"><b>${issues}</b><s>e-mail${issues > 1 ? 's' : ''} non parti${issues > 1 ? 's' : ''}</s></div>` : '',
    allergies ? `<div class="stat alert"><b>${allergies}</b><s>repas à venir avec allergie</s></div>` : '',
    billing.quotes?.new ? `<div class="stat alert"><b>${billing.quotes.new}</b><s>devis à traiter</s></div>` : '',
    // Deux repères d'argent, seulement quand ils ont quelque chose à dire :
    // une tuile « 0 € en attente » occupe la place sans rien apprendre.
    toBill ? `<div class="stat"><b>${toBill}</b><s>repas passé${toBill > 1 ? 's' : ''} à facturer</s></div>` : '',
    billing.outstanding > 0 ? `<div class="stat alert"><b>${escapeHtml(formatAmount(billing.outstanding))}</b><s>en attente de règlement</s></div>` : '',
  ].filter(Boolean).join('');
  return `<div class="summary">${cards}</div>`;
}

function calendarPanel() {
  const { year, month } = view.month;
  const today = todayISO();
  const total = daysInMonth(year, month);
  const offset = weekdayIndex(isoOf(year, month, 1));

  const cells = [];
  for (let i = 0; i < offset; i += 1) cells.push('<div class="day empty"></div>');
  for (let d = 1; d <= total; d += 1) {
    const iso = isoOf(year, month, d);
    const open = SERVICES.map((s) => slotAt(iso, s)).filter(Boolean);
    const booked = open.some((s) => s.booking_id);
    if (iso < today) { cells.push(`<div class="day past"><span>${d}</span></div>`); continue; }
    const klass = booked ? 'day booked' : open.length ? 'day free' : 'day off';
    const picked = view.picked.has(iso) ? ' picked' : '';
    const dots = open.map((s) => `<i class="dot ${escapeHtml(s.service)}"></i>`).join('');
    cells.push(`<button type="button" class="${klass}${picked}" data-date="${iso}"
      aria-pressed="${view.picked.has(iso)}"><span>${d}</span><span class="dots">${dots}</span></button>`);
  }

  return `
    <div class="panel">
      <div class="cal-head">
        <button type="button" class="nav" data-nav="-1" aria-label="Mois précédent">‹</button>
        <strong>${escapeHtml(monthLabel(year, month))}</strong>
        <button type="button" class="nav" data-nav="1" aria-label="Mois suivant">›</button>
      </div>
      <div class="weekdays">${WEEKDAYS.map((d) => `<span>${d}</span>`).join('')}</div>
      <div class="grid">${cells.join('')}</div>
      <p class="legend">
        <span><i class="is-free"></i>ouvert</span>
        <span><i class="is-booked"></i>réservé</span>
        <span><i class="dot midi" style="border-radius:50%"></i>déjeuner</span>
        <span><i class="dot soir" style="border-radius:50%"></i>dîner</span>
      </p>
      ${selectionBar()}
      <div class="selectbar" style="background:var(--paper-warm);border-color:var(--line)">
        <p>Raccourcis</p>
        <div class="actions">
          <button class="btn" data-quick="weekends">Cocher tous les week-ends</button>
          <button class="btn" data-quick="month">Cocher tout le mois</button>
        </div>
      </div>
    </div>`;
}

function selectionBar() {
  const n = view.picked.size;
  if (!n) {
    return `<p class="hint" style="margin:1rem 0 0">Cochez un ou plusieurs jours, puis ouvrez le déjeuner, le dîner, ou les deux d'un seul geste.</p>`;
  }
  return `
    <div class="selectbar">
      <p>${n} jour${n > 1 ? 's' : ''} coché${n > 1 ? 's' : ''}</p>
      <div class="actions">
        <button class="btn primary" data-open="midi">Ouvrir le déjeuner</button>
        <button class="btn primary" data-open="soir">Ouvrir le dîner</button>
        <button class="btn primary" data-open="both">Les deux</button>
        <button class="btn danger" data-close="1">Fermer</button>
        <button class="btn" data-clear="1">Décocher</button>
      </div>
    </div>`;
}

function slotsPanel() {
  const today = todayISO();
  const rows = view.slots
    .filter((s) => s.date >= today)
    .map((s) => {
      const tooSoon = view.firstBookable && s.date < view.firstBookable;
      let badge;
      if (s.booking_id) badge = `<span class="badge bad">Réservé — ${escapeHtml(s.name)} (${escapeHtml(s.guests)} couverts)</span>`;
      else if (tooSoon) badge = '<span class="badge warn">Trop proche — invisible sur le site</span>';
      else badge = '<span class="badge ok">Visible et réservable</span>';
      const close = s.booking_id ? '' : `<button class="btn danger" data-close-one="${s.id}">Fermer</button>`;
      return `<div class="slot-row">
        <strong>${escapeHtml(longDate(s.date))}</strong>
        <span class="badge neutral">${escapeHtml(SERVICE_LABEL[s.service] ?? s.service)}</span>
        ${badge}${close}
      </div>`;
    }).join('');
  return `
    <div class="panel">
      <h2>Vos créneaux — ${escapeHtml(monthLabel(view.month.year, view.month.month))}</h2>
      <p class="hint">Ce que voient vos clients, dans l'ordre.</p>
      ${rows || '<p class="hint" style="margin:0">Aucun créneau ouvert sur ce mois.</p>'}
    </div>`;
}

function mailBadge(b) {
  const states = [b.mail_client, b.mail_chef];
  if (states.every((s) => s === 'sent')) return '<span class="badge ok">e-mails envoyés</span>';
  if (states.includes('failed')) {
    const reasons = [...new Set(b.mail_error.split(' | ').filter(Boolean))];
    return `<span class="badge bad">e-mail en échec</span> <span class="hint" style="margin:0">${escapeHtml(reasons.join(' · '))}</span>`;
  }
  if (states.includes('disabled')) return '<span class="badge warn">envoi désactivé</span>';
  return '<span class="badge neutral">envoi en cours…</span>';
}

/* Une ligne, pas un tableau de bord : le chef veut savoir en passant si ce
   repas est facturé et payé. Le détail est dans le dossier. */
function billingLine(b) {
  const bill = b.billing ?? {};
  if (!b.invoice_id) return 'Pas de facture';
  if (b.invoice_status === 'draft') {
    return `Brouillon de facture — ${escapeHtml(formatAmount(b.invoice_total_cents ?? 0))}`;
  }
  const label = BILLING_STATE_LABEL[bill.state] ?? bill.state ?? '';
  const rest = bill.balance_cents;
  const tail = rest > 0 ? ` — reste ${escapeHtml(formatAmount(rest))}` : '';
  return `Facture ${escapeHtml(b.invoice_number ?? '')} — ${escapeHtml(formatAmount(bill.due_cents ?? 0))} · ${escapeHtml(label)}${tail}`;
}

function bookingsPanel() {
  const today = todayISO();
  const upcoming = view.bookings.filter((b) => b.date >= today);
  if (!upcoming.length) {
    return `<div class="panel"><h2>Réservations à venir</h2>
      <p class="hint" style="margin:0">Rien pour l'instant. Ouvrez des dates pour que vos clients puissent réserver.</p></div>`;
  }
  const cards = upcoming.map((b) => `
    <div class="booking-card">
      <div class="when">${escapeHtml(longDate(b.date))} — ${escapeHtml(SERVICE_LABEL[b.service] ?? b.service)} · ${escapeHtml(b.guests)} couverts</div>
      <p class="who"><strong>${escapeHtml(b.name)}</strong> · <a href="mailto:${escapeHtml(b.email)}">${escapeHtml(b.email)}</a>${b.phone ? ` · <a href="tel:${escapeHtml(b.phone.replace(/\s/g, ''))}">${escapeHtml(b.phone)}</a>` : ''}</p>
      <p class="meta">${escapeHtml(b.address || 'adresse non renseignée')} · ${escapeHtml(b.formula || 'formule à définir')} · réf. ${escapeHtml(b.ref)}</p>
      <p class="diet-line">${dietBadges(b.diets_detail)}</p>
      ${b.message ? `<p class="quote">« ${escapeHtml(b.message)} »</p>` : ''}
      <p class="meta">${billingLine(b)}</p>
      <div class="actions">
        ${mailBadge(b)}
        ${travelBadge(b, billing.settings.chef_address)}
        <button class="btn" data-folder-open="${b.id}">Facturation</button>
        <button class="btn danger" data-cancel="${b.id}">Annuler</button>
        <button class="btn" data-resend="${b.id}">Renvoyer les e-mails</button>
      </div>
    </div>`).join('');
  return `<div class="panel"><h2>Réservations à venir</h2><p class="hint">${upcoming.length} au total.</p>${cards}</div>`;
}

function tabBody() {
  if (view.tab === 'reglages') return settingsPanel();
  if (view.tab === 'relances') return remindersPanel();
  if (view.tab === 'devis') return quotesPanel();
  if (view.tab === 'formules') return formulasPanel();
  if (view.tab === 'facturation') return invoicesPanel();
  return `<div class="admin-split">
      <div>${calendarPanel()}</div>
      <div>${bookingsPanel()}${slotsPanel()}</div>
    </div>`;
}

function render() {
  if (!view.authenticated) { app.innerHTML = loginView(); return; }
  const mailWarn = view.mailEnabled ? '' :
    `<div class="panel" style="border-color:#e8c0b5;background:#fdf1ed;margin-bottom:1.5rem">
       <p class="error" style="margin:0">L'envoi d'e-mails est désactivé côté serveur (SMTP_HOST). Les réservations sont bien enregistrées, mais personne ne reçoit de confirmation.</p>
     </div>`;
  const tabs = TABS.map(([key, label]) =>
    `<button class="tab${view.tab === key ? ' active' : ''}" data-tab="${key}">${escapeHtml(label)}</button>`).join('');
  app.innerHTML = `
    <div class="admin-head">
      <div class="wrap">
        <h1>Votre back-office</h1>
        <div class="tools">
          <a href="/" class="btn">Voir le site</a>
          <button class="btn" data-logout="1">Déconnexion</button>
        </div>
      </div>
      <div class="wrap"><nav class="tabs">${tabs}</nav></div>
    </div>
    <div class="admin-body"><div class="wrap">
      ${view.flash ? `<div class="panel" style="margin-bottom:1.5rem;border-color:#cfdab8;background:var(--olive-soft)"><p style="margin:0;font-weight:600">${escapeHtml(view.flash)}</p></div>` : ''}
      ${view.error ? `<div class="panel" style="margin-bottom:1.5rem"><p class="error" style="margin:0" role="alert">${escapeHtml(view.error)}</p></div>` : ''}
      ${mailWarn}
      ${summary()}
      ${billing.folder ? folderPanel() : ''}
      ${tabBody()}
    </div></div>`;
}

// --- Données ------------------------------------------------------------

async function refresh() {
  const [start, end] = monthBounds();
  try {
    // Les factures sont toujours rechargées, même hors de l'onglet : le
    // résumé en tête affiche l'encours sur toutes les pages, et un encours
    // périmé est une information fausse plutôt qu'absente.
    // Les réglages accompagnent chaque rafraîchissement : le lien « Trajet »
    // des cartes en dépend, et il ne peut pas attendre que le chef passe par
    // l'onglet Réglages pour apparaître.
    const [slots, bookings, invoices, config] = await Promise.all([
      api.slots(start, end), api.bookings(), api.invoices(), api.settings(),
    ]);
    billing.settings = config;
    view.slots = slots.slots;
    view.firstBookable = slots.first_bookable;
    view.bookings = bookings.bookings;
    billing.invoices = invoices.invoices;
    billing.outstanding = invoices.outstanding_cents;
    if (view.tab === 'formules') {
      const data = await api.formulas();
      billing.formulas = data.formulas;
      billing.pricingKinds = data.pricing_kinds;
    }
    if (view.tab === 'relances') billing.reminders = await api.reminders();
    // Les devis sont TOUJOURS rechargés, même hors de l'onglet : le compte de
    // demandes à traiter s'affiche dans le résumé de tête, sur toutes les
    // pages, et un compte périmé est une information fausse plutôt qu'absente.
    const quotes = await api.quotes();
    billing.quotes = quotes;
    billing.quoteStatuses = quotes.statuses;

    if (billing.folder) {
      const id = billing.folder.booking.id;
      const booking = view.bookings.find((b) => b.id === id) ?? billing.folder.booking;
      billing.folder = { booking, data: await api.folder(id) };
    }
    view.error = '';
  } catch (err) {
    if (err.status === 401) view.authenticated = false;
    view.error = err.message;
  }
  render();
}

async function openFolder(bookingId) {
  let booking = view.bookings.find((b) => b.id === bookingId);
  if (!booking) {
    // Ouvert depuis l'onglet Facturation : la réservation peut être annulée
    // ou hors de la liste « confirmées ». On la reconstruit depuis la facture
    // plutôt que d'afficher un dossier sans en-tête.
    const invoice = billing.invoices.find((i) => i.booking_id === bookingId);
    booking = invoice ? { id: bookingId, name: invoice.name, date: invoice.date,
                          service: invoice.service, guests: invoice.guests,
                          ref: invoice.ref, formula: '' } : { id: bookingId, name: '', date: todayISO(), service: '', guests: 0, ref: '' };
  }
  billing.folder = { booking, data: await api.folder(bookingId) };
  return '';
}

async function act(fn) {
  view.busy = true;
  try {
    view.flash = (await fn()) ?? '';
    view.error = '';
  } catch (err) {
    view.error = err.message;
    view.flash = '';
    if (err.status === 401) view.authenticated = false;
  } finally {
    view.busy = false;
  }
  await refresh();
}

function pickedDates() {
  return [...view.picked].sort();
}

async function openPicked(which) {
  const services = which === 'both' ? SERVICES : [which];
  const items = pickedDates().flatMap((date) => services.map((service) => ({ date, service, note: '' })));
  const res = await api.openSlots(items);
  view.picked.clear();
  const already = res.requested - res.created;
  // Ne jamais laisser croire qu'on a fait plus que fait : les créneaux déjà
  // ouverts sont comptés à part, pas silencieusement absorbés.
  return already
    ? `${res.created} créneau(x) ouvert(s), ${already} l'étaient déjà.`
    : `${res.created} créneau(x) ouvert(s).`;
}

async function closePicked() {
  const dates = new Set(pickedDates());
  const target = view.slots.filter((s) => dates.has(s.date));
  const closable = target.filter((s) => !s.booking_id);
  const booked = target.length - closable.length;
  for (const slot of closable) await api.closeSlot(slot.id);
  view.picked.clear();
  if (!target.length) return 'Aucun créneau ouvert sur les jours cochés.';
  return booked
    ? `${closable.length} créneau(x) fermé(s). ${booked} réservé(s) laissé(s) en place — annulez la réservation pour les libérer.`
    : `${closable.length} créneau(x) fermé(s).`;
}

// --- Événements ---------------------------------------------------------

app.addEventListener('submit', async (event) => {
  if (event.target.id === 'draft-form') {
    event.preventDefault();
    captureDraft();
    const id = billing.folder.data.invoice.id;
    act(async () => { await api.updateInvoice(id, draftPayload()); return 'Brouillon enregistré.'; });
    return;
  }

  if (event.target.id === 'payment-form') {
    event.preventDefault();
    const form = event.target;
    const cents = parseAmount(form.elements.amount.value);
    if (cents === null || cents === 0) {
      // Refuser ici plutôt que d'envoyer : un montant mal tapé qui part en
      // 0 € s'inscrit dans l'historique et fausse un solde.
      view.error = "Montant illisible. Écrivez-le en euros, par exemple 120 ou 120,50.";
      view.flash = '';
      render();
      return;
    }
    const body = {
      amount: form.elements.amount.value,
      kind: form.elements.kind.value,
      method: form.elements.method.value,
      received_on: form.elements.received_on.value,
      note: form.elements.note.value,
    };
    act(async () => {
      const res = await api.addPayment(Number(form.dataset.booking), body);
      return `Encaissement de ${formatAmount(res.amount_cents)} enregistré.`;
    });
    return;
  }

  if (event.target.id === 'address-form') {
    event.preventDefault();
    const form = event.target;
    act(async () => {
      await api.updateAddress(Number(form.dataset.booking), {
        address: form.elements.address.value,
        city: form.elements.city.value,
      });
      billing.editingAddress = false;
      return "Adresse corrigée. L'estimation de trajet a été effacée : relancez-la.";
    });
    return;
  }

  if (event.target.id === 'settings-form') {
    event.preventDefault();
    const address = event.target.elements.chef_address.value;
    const area = event.target.elements.area_postcodes.value;
    act(async () => {
      await api.saveSettings({ chef_address: address, area_postcodes: area });
      billing.settings.chef_address = address.trim();
      billing.settings.area_postcodes = area.trim();
      // Le message nomme l'effet de la zone, pas le fait d'avoir enregistré :
      // « vide » veut dire « plus aucune restriction », et le chef doit le
      // lire au moment où il le fait, pas le découvrir sur une réservation.
      return area.trim()
        ? `Réglages enregistrés. Zone appliquée : ${area.trim()}.`
        : 'Réglages enregistrés. Aucune restriction de zone : toutes les communes peuvent réserver.';
    });
    return;
  }

  const quoteForm = event.target.closest('[data-quote-form]');
  if (quoteForm) {
    event.preventDefault();
    const id = Number(quoteForm.dataset.quoteForm);
    const body = { status: quoteForm.elements.status.value, note: quoteForm.elements.note.value };
    act(async () => {
      await api.updateQuote(id, body);
      billing.editingQuote = null;
      return 'Demande mise à jour.';
    });
    return;
  }

  const formulaForm = event.target.closest('[data-formula-form]');
  if (formulaForm) {
    event.preventDefault();
    const f = formulaForm.elements;
    const body = {
      name: f.name.value.trim(),
      description: f.description.value.trim(),
      pricing: f.pricing.value,
      price: f.price.value || '0',
      min_guests: Number(f.min_guests.value) || 0,
      active: f.active.checked,
      position: Number(f.position.value) || 0,
    };
    const id = formulaForm.dataset.formulaForm;
    act(async () => {
      if (id === 'new') await api.createFormula(body);
      else await api.updateFormula(Number(id), body);
      billing.editingFormula = null;
      return id === 'new' ? 'Formule créée.' : 'Formule mise à jour.';
    });
    return;
  }

  if (event.target.id !== 'login-form') return;
  event.preventDefault();
  const password = event.target.elements.password.value;
  view.busy = true; render();
  try {
    await api.login(password);
    view.authenticated = true;
    view.error = '';
    await refresh();
  } catch (err) {
    view.error = err.message;
    view.busy = false;
    render();
  }
});

app.addEventListener('click', (event) => {
  const tab = event.target.closest('[data-tab]');
  if (tab) {
    view.tab = tab.dataset.tab;
    view.flash = '';
    refresh();
    return;
  }

  const openFolderBtn = event.target.closest('[data-folder-open]');
  if (openFolderBtn) {
    act(() => openFolder(Number(openFolderBtn.dataset.folderOpen)));
    return;
  }

  if (event.target.closest('[data-folder-close]')) {
    billing.folder = null;
    view.flash = '';
    render();
    return;
  }

  const addLine = event.target.closest('[data-line-add]');
  if (addLine) {
    captureDraft();
    billing.folder.data.invoice.lines.push({ label: '', quantity: 1, unit_cents: 0 });
    render();
    return;
  }

  const removeLine = event.target.closest('[data-line-remove]');
  if (removeLine) {
    captureDraft();
    const lines = billing.folder.data.invoice.lines;
    // Toujours au moins une ligne : une facture sans ligne ne s'émet pas, et
    // un éditeur vide n'offre plus aucune prise pour repartir.
    if (lines.length > 1) lines.splice(Number(removeLine.dataset.lineRemove), 1);
    render();
    return;
  }

  const createInvoice = event.target.closest('[data-invoice-create]');
  if (createInvoice) {
    act(async () => {
      await api.createInvoice(Number(createInvoice.dataset.invoiceCreate));
      return 'Brouillon créé. Vérifiez les lignes avant d\'émettre.';
    });
    return;
  }

  const issue = event.target.closest('[data-invoice-issue]');
  if (issue) {
    captureDraft();
    const id = Number(issue.dataset.invoiceIssue);
    if (!confirm("Émettre la facture ?\n\nElle reçoit un numéro définitif et ne pourra plus être modifiée.")) return;
    act(async () => {
      // Enregistrer avant d'émettre : sinon on figerait la version d'avant la
      // dernière frappe, sans que rien ne le signale.
      await api.updateInvoice(id, draftPayload());
      const res = await api.issueInvoice(id);
      return `Facture ${res.number} émise (${formatAmount(res.total_cents)}). Vous pouvez l'envoyer au client.`;
    });
    return;
  }

  const cancelInvoice = event.target.closest('[data-invoice-cancel]');
  if (cancelInvoice) {
    const id = Number(cancelInvoice.dataset.invoiceCancel);
    const isDraft = billing.folder?.data?.invoice?.editable;
    const reason = isDraft ? ''
      : prompt("Annuler cette facture ?\nSon numéro reste consommé et le motif lui reste attaché.\n\nMotif :");
    if (!isDraft && reason === null) return;
    act(async () => {
      await api.cancelInvoice(id, reason ?? '');
      return isDraft ? 'Brouillon jeté.' : 'Facture annulée. Vous pouvez en créer une nouvelle.';
    });
    return;
  }

  const send = event.target.closest('[data-invoice-send]');
  if (send) {
    act(async () => {
      const res = await api.sendInvoice(Number(send.dataset.invoiceSend));
      return `Facture ${res.queued} en cours d'envoi. Le résultat s'affichera ici.`;
    });
    return;
  }

  const deletePayment = event.target.closest('[data-payment-delete]');
  if (deletePayment) {
    if (!confirm('Supprimer cet encaissement ? Le solde sera recalculé.')) return;
    act(async () => {
      await api.deletePayment(Number(deletePayment.dataset.paymentDelete));
      return 'Encaissement supprimé.';
    });
    return;
  }

  if (event.target.closest('[data-reminders-run]')) {
    act(async () => {
      const r = await api.runReminders();
      // Le compte est rendu tel quel, y compris à zéro : « rien à envoyer »
      // et « l'envoi ne marche pas » ne doivent pas se ressembler.
      return `${r.planned} planifié(s), ${r.sent} envoyé(s), ${r.skipped} abandonné(s), ${r.failed} en échec.`;
    });
    return;
  }

  const quoteEdit = event.target.closest('[data-quote-edit]');
  if (quoteEdit) { billing.editingQuote = Number(quoteEdit.dataset.quoteEdit); render(); return; }
  if (event.target.closest('[data-quote-cancel]')) { billing.editingQuote = null; render(); return; }

  const quoteSlot = event.target.closest('[data-quote-slot]');
  if (quoteSlot) {
    act(async () => {
      const r = await api.openQuoteSlot(Number(quoteSlot.dataset.quoteSlot));
      // Ouvert n'est pas réservé : le client doit encore confirmer depuis le
      // site, ce qui lui envoie sa vraie confirmation. Le dire évite que le
      // chef considère la date comme acquise.
      return r.opened
        ? "Créneau ouvert. Envoyez le lien du site au client : c'est lui qui confirme."
        : "Ce créneau était déjà ouvert. Envoyez le lien du site au client.";
    });
    return;
  }

  const formulaNew = event.target.closest('[data-formula-new]');
  if (formulaNew) { billing.editingFormula = 'new'; render(); return; }

  const formulaEdit = event.target.closest('[data-formula-edit]');
  if (formulaEdit) { billing.editingFormula = Number(formulaEdit.dataset.formulaEdit); render(); return; }

  if (event.target.closest('[data-formula-cancel]')) { billing.editingFormula = null; render(); return; }

  const formulaDelete = event.target.closest('[data-formula-delete]');
  if (formulaDelete) {
    if (!confirm('Supprimer cette formule ? Elle disparaît du site.')) return;
    act(async () => { await api.deleteFormula(Number(formulaDelete.dataset.formulaDelete)); return 'Formule supprimée.'; });
    return;
  }

  const nav = event.target.closest('[data-nav]');
  if (nav) {
    let { year, month } = view.month;
    month += Number(nav.dataset.nav);
    if (month < 1) { month = 12; year -= 1; }
    if (month > 12) { month = 1; year += 1; }
    view.month = { year, month };
    view.picked.clear();
    view.flash = '';
    refresh();
    return;
  }

  const day = event.target.closest('[data-date]');
  if (day) {
    const iso = day.dataset.date;
    if (view.picked.has(iso)) view.picked.delete(iso); else view.picked.add(iso);
    view.flash = '';
    render();
    return;
  }

  const quick = event.target.closest('[data-quick]');
  if (quick) {
    const { year, month } = view.month;
    const today = todayISO();
    for (let d = 1; d <= daysInMonth(year, month); d += 1) {
      const iso = isoOf(year, month, d);
      if (iso < today) continue;
      if (quick.dataset.quick === 'month' || weekdayIndex(iso) >= 5) view.picked.add(iso);
    }
    render();
    return;
  }

  if (event.target.closest('[data-clear]')) { view.picked.clear(); render(); return; }

  const open = event.target.closest('[data-open]');
  if (open) { act(() => openPicked(open.dataset.open)); return; }

  if (event.target.closest('[data-close]')) { act(closePicked); return; }

  const closeOne = event.target.closest('[data-close-one]');
  if (closeOne) {
    act(async () => { await api.closeSlot(Number(closeOne.dataset.closeOne)); return 'Créneau fermé.'; });
    return;
  }

  const cancel = event.target.closest('[data-cancel]');
  if (cancel) {
    const reason = prompt("Annuler cette réservation ? Le client sera prévenu par e-mail.\nMotif (facultatif, repris dans l'e-mail) :");
    if (reason === null) return;
    act(async () => {
      const r = await api.cancel(Number(cancel.dataset.cancel), reason);
      return `Réservation ${r.cancelled} annulée, le client est prévenu et la date est de nouveau libre.`;
    });
    return;
  }

  const addressEdit = event.target.closest('[data-address-edit]');
  if (addressEdit) { billing.editingAddress = true; view.flash = ''; render(); return; }
  if (event.target.closest('[data-address-cancel]')) { billing.editingAddress = false; render(); return; }

  const travelBtn = event.target.closest('[data-travel]');
  if (travelBtn) {
    act(async () => {
      const r = await api.travel(Number(travelBtn.dataset.travel));
      // Le motif d'échec est rendu tel quel : le chef doit pouvoir distinguer
      // « adresse incomplète », qu'il peut corriger, de « service
      // injoignable », où il n'y a qu'à réessayer.
      if (r.error) return `Trajet non estimé : ${r.error}`;
      return r.approximate
        ? `Trajet approximatif : ≈ ${r.label}${r.km ? `, ${r.km} km` : ''} — adresse exacte introuvable, estimé depuis le centre de la commune.`
        : `Trajet estimé : ${r.label}${r.km ? `, ${r.km} km` : ''} en voiture, sans trafic.`;
    });
    return;
  }

  const resend = event.target.closest('[data-resend]');
  if (resend) {
    act(async () => { await api.resend(Number(resend.dataset.resend)); return 'E-mails relancés.'; });
    return;
  }

  if (event.target.closest('[data-logout]')) {
    act(async () => { await api.logout(); view.authenticated = false; return ''; });
  }
});

async function start() {
  const now = new Date();
  view.month = { year: now.getFullYear(), month: now.getMonth() + 1 };
  try {
    const session = await api.session();
    view.authenticated = session.authenticated;
    view.configured = session.configured;
    view.mailEnabled = session.mail_enabled;
  } catch { /* on retombe sur l'écran de connexion */ }
  if (view.authenticated) await refresh();
  else render();
}

start();
