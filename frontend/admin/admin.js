import { request } from '../js/api.js';
import { escapeHtml, longDate, monthLabel, isoOf, daysInMonth, weekdayIndex,
         todayISO, SERVICE_LABEL } from '../js/util.js';

const app = document.getElementById('app');
const WEEKDAYS = ['L', 'M', 'M', 'J', 'V', 'S', 'D'];
const SERVICES = ['midi', 'soir'];

const view = {
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
  const cards = [
    `<div class="stat"><b>${upcoming.length}</b><s>réservation${upcoming.length > 1 ? 's' : ''} à venir</s></div>`,
    `<div class="stat"><b>${covers}</b><s>couverts à préparer</s></div>`,
    `<div class="stat"><b>${openFree}</b><s>créneau${openFree > 1 ? 'x' : ''} libre${openFree > 1 ? 's' : ''} ce mois</s></div>`,
    issues ? `<div class="stat alert"><b>${issues}</b><s>e-mail${issues > 1 ? 's' : ''} non parti${issues > 1 ? 's' : ''}</s></div>` : '',
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
      ${b.message ? `<p class="quote">« ${escapeHtml(b.message)} »</p>` : ''}
      <div class="actions">
        ${mailBadge(b)}
        <button class="btn danger" data-cancel="${b.id}">Annuler</button>
        <button class="btn" data-resend="${b.id}">Renvoyer les e-mails</button>
      </div>
    </div>`).join('');
  return `<div class="panel"><h2>Réservations à venir</h2><p class="hint">${upcoming.length} au total.</p>${cards}</div>`;
}

function render() {
  if (!view.authenticated) { app.innerHTML = loginView(); return; }
  const mailWarn = view.mailEnabled ? '' :
    `<div class="panel" style="border-color:#e8c0b5;background:#fdf1ed;margin-bottom:1.5rem">
       <p class="error" style="margin:0">L'envoi d'e-mails est désactivé côté serveur (SMTP_HOST). Les réservations sont bien enregistrées, mais personne ne reçoit de confirmation.</p>
     </div>`;
  app.innerHTML = `
    <div class="admin-head">
      <div class="wrap">
        <h1>Votre back-office</h1>
        <div class="tools">
          <a href="/" class="btn">Voir le site</a>
          <button class="btn" data-logout="1">Déconnexion</button>
        </div>
      </div>
    </div>
    <div class="admin-body"><div class="wrap">
      ${view.flash ? `<div class="panel" style="margin-bottom:1.5rem;border-color:#cfdab8;background:var(--olive-soft)"><p style="margin:0;font-weight:600">${escapeHtml(view.flash)}</p></div>` : ''}
      ${view.error ? `<div class="panel" style="margin-bottom:1.5rem"><p class="error" style="margin:0" role="alert">${escapeHtml(view.error)}</p></div>` : ''}
      ${mailWarn}
      ${summary()}
      <div class="admin-split">
        <div>${calendarPanel()}</div>
        <div>${bookingsPanel()}${slotsPanel()}</div>
      </div>
    </div></div>`;
}

// --- Données ------------------------------------------------------------

async function refresh() {
  const [start, end] = monthBounds();
  try {
    const [slots, bookings] = await Promise.all([api.slots(start, end), api.bookings()]);
    view.slots = slots.slots;
    view.firstBookable = slots.first_bookable;
    view.bookings = bookings.bookings;
    view.error = '';
  } catch (err) {
    if (err.status === 401) view.authenticated = false;
    view.error = err.message;
  }
  render();
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
