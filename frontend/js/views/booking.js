import { escapeHtml, longDate, monthLabel, isoOf, daysInMonth, weekdayIndex, SERVICE_LABEL } from '../util.js';
import { state, slotsByDate } from '../state.js';

const WEEKDAYS = ['L', 'M', 'M', 'J', 'V', 'S', 'D'];

function calendar() {
  const { year, month } = state.month;
  const byDate = slotsByDate();
  const total = daysInMonth(year, month);
  const offset = weekdayIndex(isoOf(year, month, 1));

  const cells = [];
  for (let i = 0; i < offset; i += 1) cells.push('<div class="day empty"></div>');
  for (let day = 1; day <= total; day += 1) {
    const iso = isoOf(year, month, day);
    const slots = byDate.get(iso) ?? [];
    const selected = state.selectedDate === iso ? ' selected' : '';
    if (!slots.length) {
      cells.push(`<div class="day off"><span>${day}</span></div>`);
      continue;
    }
    const dots = slots.map((s) => `<i class="dot ${escapeHtml(s.service)}"></i>`).join('');
    cells.push(
      `<button class="day free${selected}" data-date="${iso}" type="button"
         aria-label="${escapeHtml(longDate(iso))} — ${slots.length} créneau(x)">
         <span>${day}</span><span class="dots">${dots}</span>
       </button>`);
  }

  // Navigation is bounded by what the chef actually opened: there is no point
  // letting a visitor page through twelve empty months.
  const dates = state.slots.map((s) => s.date).sort();
  const min = dates[0] ?? isoOf(year, month, 1);
  const max = dates[dates.length - 1] ?? isoOf(year, month, total);
  const cur = isoOf(year, month, 1);
  const prevDisabled = cur <= min.slice(0, 7) + '-01' ? ' disabled' : '';
  const nextDisabled = cur >= max.slice(0, 7) + '-01' ? ' disabled' : '';

  return `
    <div class="calendar">
      <div class="cal-head">
        <button type="button" class="nav" data-nav="-1"${prevDisabled} aria-label="Mois précédent">‹</button>
        <strong>${escapeHtml(monthLabel(year, month))}</strong>
        <button type="button" class="nav" data-nav="1"${nextDisabled} aria-label="Mois suivant">›</button>
      </div>
      <div class="weekdays">${WEEKDAYS.map((d) => `<span>${d}</span>`).join('')}</div>
      <div class="grid">${cells.join('')}</div>
      <p class="legend"><i class="dot midi"></i> déjeuner &nbsp; <i class="dot soir"></i> dîner</p>
    </div>`;
}

function servicePicker() {
  if (!state.selectedDate) return '';
  const slots = slotsByDate().get(state.selectedDate) ?? [];
  const buttons = slots.map((slot) => {
    const active = state.selectedSlot?.id === slot.id ? ' active' : '';
    const note = slot.note ? `<em>${escapeHtml(slot.note)}</em>` : '';
    return `<button type="button" class="service${active}" data-slot="${slot.id}">
      ${escapeHtml(SERVICE_LABEL[slot.service] ?? slot.service)}${note}</button>`;
  }).join('');
  return `
    <div class="picker">
      <p class="picked">${escapeHtml(longDate(state.selectedDate))}</p>
      <div class="services">${buttons}</div>
    </div>`;
}

function form() {
  if (!state.selectedSlot) return '';
  const cfg = state.content.booking ?? {};
  const formulas = (state.content.formulas ?? []).map((f) =>
    `<option value="${escapeHtml(f.name)}"${state.form.formula === f.name ? ' selected' : ''}>${escapeHtml(f.name)}</option>`
  ).join('');
  const f = state.form;
  const notice = cfg.notice ? `<p class="notice">${escapeHtml(cfg.notice)}</p>` : '';

  return `
    <form class="booking-form" id="booking-form" novalidate>
      <div class="row">
        <label>Votre nom<input name="name" value="${escapeHtml(f.name)}" required maxlength="80" autocomplete="name"></label>
        <label>Convives<input name="guests" type="number" inputmode="numeric" value="${escapeHtml(f.guests)}"
          min="${escapeHtml(cfg.min_guests ?? 1)}" max="${escapeHtml(cfg.max_guests ?? 100)}" required></label>
      </div>
      <div class="row">
        <label>E-mail<input name="email" type="email" value="${escapeHtml(f.email)}" required maxlength="160" autocomplete="email"></label>
        <label>Téléphone<input name="phone" type="tel" value="${escapeHtml(f.phone)}" maxlength="40" autocomplete="tel"></label>
      </div>
      <label>Adresse du repas<input name="address" value="${escapeHtml(f.address)}" maxlength="300" autocomplete="street-address"></label>
      ${formulas ? `<label>Formule envisagée<select name="formula"><option value="">À définir ensemble</option>${formulas}</select></label>` : ''}
      <label>Allergies, envies, contraintes<textarea name="message" rows="3" maxlength="2000">${escapeHtml(f.message)}</textarea></label>
      ${notice}
      ${state.error ? `<p class="error" role="alert">${escapeHtml(state.error)}</p>` : ''}
      <button type="submit" class="cta" ${state.submitting ? 'disabled' : ''}>
        ${state.submitting ? 'Envoi…' : 'Confirmer la réservation'}
      </button>
    </form>`;
}

function confirmation() {
  const c = state.confirmation;
  const warn = c.mail_sent
    ? `<p>Un e-mail de confirmation vient de vous être envoyé.</p>`
    : `<p class="warn">Votre date est bien bloquée, mais l'e-mail de confirmation n'a pas pu partir.
        Notez votre référence — le chef est prévenu et vous recontactera.</p>`;
  return `
    <div class="confirmed">
      <p class="check">Réservation confirmée</p>
      <p class="big">${escapeHtml(longDate(c.date))} — ${escapeHtml(SERVICE_LABEL[c.service] ?? c.service)}</p>
      <p class="ref">Référence <strong>${escapeHtml(c.ref)}</strong></p>
      ${warn}
      <button type="button" class="link" data-reset="1">Réserver une autre date</button>
    </div>`;
}

export function renderBooking() {
  if (state.confirmation) return confirmation();
  if (state.loadError) {
    return `<p class="error" role="alert">${escapeHtml(state.loadError)}</p>`;
  }
  if (!state.slots.length) {
    const contact = state.content?.contact?.email ?? '';
    const mail = contact
      ? ` Écrivez-moi à <a href="mailto:${escapeHtml(contact)}">${escapeHtml(contact)}</a> et on trouvera une date.`
      : '';
    return `<p class="empty-cal">Aucune date n'est ouverte pour le moment.${mail}</p>`;
  }
  return calendar() + servicePicker() + form();
}
