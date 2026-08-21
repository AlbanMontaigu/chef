import { escapeHtml, longDate, weekdayName, dayNumber, shortMonth,
         monthKey, monthLabelFromKey, SERVICE_LABEL } from '../util.js';
import { state, slotsByDate } from '../state.js';

function stepper() {
  const step = state.confirmation ? 3 : state.selectedSlot ? 2 : 1;
  const cell = (n, label) => {
    const cls = step > n ? 'done' : step === n ? 'now' : '';
    return `<span class="${cls}"><i>${step > n ? '✓' : n}</i>${label}</span>`;
  };
  return `<div class="stepper">
    ${cell(1, 'La date')}<div class="sep"></div>
    ${cell(2, 'Vos infos')}<div class="sep"></div>
    ${cell(3, 'Confirmé')}
  </div>`;
}

/* Une liste de dates plutôt qu'une grille mensuelle : quand cinq dates sont
   ouvertes, une grille de trente cases presque vides donne l'impression d'un
   agenda désert, là où une liste courte se lit et se clique. */
function dateList() {
  const byDate = slotsByDate();
  const groups = new Map();
  for (const [date, slots] of byDate) {
    const key = monthKey(date);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ date, slots });
  }

  return [...groups.entries()].map(([key, days]) => {
    const cards = days.map(({ date, slots }) => {
      const active = state.selectedDate === date ? ' active' : '';
      const services = slots.map((s) => SERVICE_LABEL[s.service] ?? s.service).join(' · ');
      const note = slots.find((s) => s.note)?.note ?? '';
      return `
        <button type="button" class="date-card${active}" data-date="${date}">
          <span class="date-badge"><b>${dayNumber(date)}</b><s>${escapeHtml(shortMonth(date))}</s></span>
          <span class="date-main">
            <span class="date-day">${escapeHtml(weekdayName(date))}</span>
            <span class="date-services">${escapeHtml(services)}</span>
            ${note ? `<span class="date-note">${escapeHtml(note)}</span>` : ''}
          </span>
        </button>`;
    }).join('');
    return `<div class="month-group">
      <h4>${escapeHtml(monthLabelFromKey(key))}</h4>
      <div class="date-list">${cards}</div>
    </div>`;
  }).join('');
}

function servicePicker() {
  if (!state.selectedDate) return '';
  const slots = slotsByDate().get(state.selectedDate) ?? [];
  if (slots.length === 1 && state.selectedSlot) return '';
  const buttons = slots.map((slot) => {
    const active = state.selectedSlot?.id === slot.id ? ' active' : '';
    return `<button type="button" class="service${active}" data-slot="${slot.id}">
      ${escapeHtml(SERVICE_LABEL[slot.service] ?? slot.service)}</button>`;
  }).join('');
  return `<div class="services" id="services">${buttons}</div>`;
}

function chosenBar() {
  const slot = state.selectedSlot;
  return `<div class="chosen">
    <p>${escapeHtml(longDate(slot.date))} — ${escapeHtml(SERVICE_LABEL[slot.service] ?? slot.service)}</p>
    <button type="button" class="link" data-change="1">changer de date</button>
  </div>`;
}

function form() {
  const cfg = state.content.booking ?? {};
  const f = state.form;
  // La valeur envoyée est l'identifiant de la formule, pas son libellé : le
  // chef peut renommer une formule, la réservation doit rester rattachée à la
  // bonne. Le serveur fige le libellé au moment de l'enregistrement.
  const options = (state.content.formulas ?? []).map((x) =>
    `<option value="${escapeHtml(x.id)}"${f.formula === x.id ? ' selected' : ''}>${escapeHtml(x.name)}${x.price ? ` — ${escapeHtml(x.price)}` : ''}</option>`
  ).join('');
  return `
    ${chosenBar()}
    <form class="booking-form" id="booking-form" novalidate>
      <div class="row">
        <label>Votre nom<input name="name" value="${escapeHtml(f.name)}" required maxlength="80" autocomplete="name" placeholder="Élodie Martin"></label>
        <label>Nombre de convives<input name="guests" type="number" inputmode="numeric" value="${escapeHtml(f.guests)}"
          min="${escapeHtml(cfg.min_guests ?? 1)}" max="${escapeHtml(cfg.max_guests ?? 100)}" required placeholder="6"></label>
      </div>
      <div class="row">
        <label>E-mail<input name="email" type="email" value="${escapeHtml(f.email)}" required maxlength="160" autocomplete="email" placeholder="vous@exemple.fr"></label>
        <label>Téléphone<input name="phone" type="tel" value="${escapeHtml(f.phone)}" maxlength="40" autocomplete="tel" placeholder="06 12 34 56 78"></label>
      </div>
      <div class="row">
        <label>Adresse du repas<input name="address" value="${escapeHtml(f.address)}" maxlength="300" autocomplete="street-address" placeholder="12 rue de l'Église"></label>
        <label>Code postal et ville<input name="city" value="${escapeHtml(f.city)}" maxlength="120" autocomplete="address-level2" placeholder="44000 Nantes"></label>
      </div>
      ${options ? `<label>Formule envisagée<select name="formula"><option value="">À définir ensemble</option>${options}</select></label>` : ''}
      <label>Allergies, envies, contraintes<textarea name="message" rows="3" maxlength="2000" placeholder="Un invité végétarien, une cuisine sans four…">${escapeHtml(f.message)}</textarea></label>
      ${cfg.notice ? `<p class="notice">${escapeHtml(cfg.notice)}</p>` : ''}
      ${state.error ? `<p class="error" role="alert">${escapeHtml(state.error)}</p>` : ''}
      <button type="submit" class="cta" ${state.submitting ? 'disabled' : ''}>
        ${state.submitting ? 'Envoi…' : 'Confirmer la réservation'}
      </button>
    </form>`;
}

function confirmation() {
  const c = state.confirmation;
  const mail = c.mail_sent
    ? '<p class="notice">Un e-mail de confirmation vient de vous être envoyé.</p>'
    : `<p class="warn">Votre date est bien bloquée, mais l'e-mail de confirmation n'a pas pu partir.
       Notez votre référence — le chef est prévenu et vous recontactera.</p>`;
  return `
    <div class="confirmed">
      <div class="seal">✓</div>
      <h3>C'est noté, à très bientôt</h3>
      <p class="big">${escapeHtml(longDate(c.date))} — ${escapeHtml(SERVICE_LABEL[c.service] ?? c.service)}</p>
      <p class="ref">Référence ${escapeHtml(c.ref)}</p>
      ${mail}
      <p style="margin-top:1.25rem"><button type="button" class="link" data-reset="1">Réserver une autre date</button></p>
    </div>`;
}

export function renderBooking() {
  if (state.confirmation) return stepper() + confirmation();
  if (state.loadError) return `<p class="error" role="alert">${escapeHtml(state.loadError)}</p>`;

  if (!state.slots.length) {
    const mail = state.content?.contact?.email ?? '';
    const invite = mail
      ? ` Écrivez-moi à <a href="mailto:${escapeHtml(mail)}">${escapeHtml(mail)}</a> et on trouvera une date ensemble.`
      : ' Revenez bientôt, de nouvelles dates arrivent régulièrement.';
    return `<p class="empty-cal">Aucune date n'est ouverte pour le moment.${invite}</p>`;
  }

  if (state.selectedSlot) return stepper() + form();
  return stepper() + dateList() + servicePicker();
}
