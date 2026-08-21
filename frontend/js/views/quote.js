/* Demande de devis : le chemin pour tout ce qui n'entre pas dans le calendrier.
 *
 * Le calendrier ne montre que les créneaux déjà ouverts. Une date non ouverte,
 * un mariage, un buffet de quarante personnes : rien de tout cela n'avait de
 * chemin, et la demande se perdait — ou n'arrivait jamais.
 *
 * Ce formulaire demande beaucoup moins que la réservation : ni date, ni
 * adresse, ni nombre exact de convives. Chaque champ obligatoire de plus est
 * une demande qui n'arrive pas.
 */

import { escapeHtml, dietBadges } from '../util.js';
import { state } from '../state.js';

function dietPicker() {
  const list = state.content.diets ?? [];
  if (!list.length) return '';
  const boxes = list.map((d) => {
    const on = state.quoteDiets.has(d.id);
    return `<div class="diet${on ? ' on' : ''}">
      <label><input type="checkbox" data-quote-diet="${escapeHtml(d.id)}"${on ? ' checked' : ''}>
        <span>${escapeHtml(d.label)}</span></label>
    </div>`;
  }).join('');
  // Sans compteur ici, contrairement à la réservation : à ce stade le nombre de
  // convives est souvent lui-même approximatif, et demander « combien de
  // végétariens » avant de savoir combien on est à table ne veut rien dire.
  return `<fieldset class="diets">
    <legend>Contraintes alimentaires connues</legend>
    <p class="hint">Ce que vous savez déjà. On affinera ensemble.</p>
    <div class="diet-list">${boxes}</div>
  </fieldset>`;
}

function confirmation() {
  const c = state.quoteConfirmation;
  const mail = c.mail_sent
    ? '<p class="notice">Un accusé de réception vient de vous être envoyé.</p>'
    : `<p class="warn">Votre demande est bien arrivée, mais l'accusé de réception n'a pas pu
       partir. Notez votre référence — le chef est prévenu et vous recontactera.</p>`;
  return `
    <div class="confirmed">
      <div class="seal">✓</div>
      <h3>Votre demande est partie</h3>
      <p class="ref">Référence ${escapeHtml(c.ref)}</p>
      ${mail}
      <p class="notice"><strong>Aucune date n'est bloquée pour l'instant</strong> — c'est une
        demande, pas une réservation. Le chef vous répond sous deux jours ouvrés et vous
        fixez une date ensemble.</p>
      <p style="margin-top:1.25rem"><button type="button" class="link" data-quote-reset="1">Faire une autre demande</button></p>
    </div>`;
}

export function renderQuote() {
  if (state.quoteConfirmation) return confirmation();
  const q = state.quoteForm;
  const occasions = (state.content.occasions ?? []).map((o) =>
    `<option value="${escapeHtml(o.id)}"${q.occasion === o.id ? ' selected' : ''}>${escapeHtml(o.label)}</option>`).join('');
  const formulas = (state.content.formulas ?? []).map((f) =>
    `<option value="${escapeHtml(f.id)}"${q.formula === f.id ? ' selected' : ''}>${escapeHtml(f.name)}</option>`).join('');
  return `
    <form class="booking-form" id="quote-form" novalidate>
      <div class="row">
        <label>Votre nom<input name="name" value="${escapeHtml(q.name)}" required maxlength="80" autocomplete="name" placeholder="Élodie Martin"></label>
        <label>E-mail<input name="email" type="email" value="${escapeHtml(q.email)}" required maxlength="160" autocomplete="email" placeholder="vous@exemple.fr"></label>
      </div>
      <div class="row">
        <label>Téléphone<input name="phone" type="tel" value="${escapeHtml(q.phone)}" maxlength="40" autocomplete="tel" placeholder="06 12 34 56 78"></label>
        <label>Commune<input name="city" value="${escapeHtml(q.city)}" maxlength="120" autocomplete="address-level2" placeholder="44000 Nantes"></label>
      </div>
      <div class="row">
        <label>Date souhaitée <span class="opt">si vous en avez une</span>
          <input name="wanted_date" type="date" value="${escapeHtml(q.wanted_date)}"></label>
        <label>Moment
          <select name="service">
            <option value=""${q.service === '' ? ' selected' : ''}>Peu importe</option>
            <option value="midi"${q.service === 'midi' ? ' selected' : ''}>Déjeuner</option>
            <option value="soir"${q.service === 'soir' ? ' selected' : ''}>Dîner</option>
          </select></label>
      </div>
      <label>Sinon, dites-le avec vos mots <span class="opt">facultatif</span>
        <input name="flexibility" value="${escapeHtml(q.flexibility)}" maxlength="200"
               placeholder="Un samedi de juin, plutôt en fin de mois"></label>
      <div class="row">
        <label>Nombre de convives <span class="opt">même approximatif</span>
          <input name="guests" type="number" inputmode="numeric" min="0" max="500" value="${escapeHtml(q.guests)}" placeholder="25"></label>
        <label>Occasion
          <select name="occasion"><option value="">À préciser</option>${occasions}</select></label>
      </div>
      ${formulas ? `<label>Une formule vous a tapé dans l'œil ?
        <select name="formula"><option value="">Aucune en particulier</option>${formulas}</select></label>` : ''}
      ${dietPicker()}
      <label>Votre projet<textarea name="message" rows="4" maxlength="2000"
        placeholder="Un buffet dînatoire pour les 40 ans de mon mari, une trentaine de personnes, dans notre jardin…">${escapeHtml(q.message)}</textarea></label>
      ${state.quoteDiets.size ? `<p class="diet-line">${dietBadges([...state.quoteDiets].map((id) => {
        const d = (state.content.diets ?? []).find((x) => x.id === id);
        return { ...d, count: 1 };
      }))}</p>` : ''}
      ${state.quoteError ? `<p class="error" role="alert">${escapeHtml(state.quoteError)}</p>` : ''}
      <button type="submit" class="cta" ${state.quoteSubmitting ? 'disabled' : ''}>
        ${state.quoteSubmitting ? 'Envoi…' : 'Envoyer ma demande'}
      </button>
      <p class="notice">Sans engagement, et sans date bloquée : c'est une demande de devis.</p>
    </form>`;
}
