import { escapeHtml } from '../util.js';

function formulaCard(formula) {
  const min = formula.min_guests
    ? `<p class="formula-min">à partir de ${escapeHtml(formula.min_guests)} convives</p>` : '';
  return `
    <article class="formula">
      <h3>${escapeHtml(formula.name)}</h3>
      <p class="formula-desc">${escapeHtml(formula.description)}</p>
      <p class="formula-price">${escapeHtml(formula.price)}</p>
      ${min}
    </article>`;
}

function steps(section) {
  const items = (section.steps ?? []).map((s) => `<li>${escapeHtml(s)}</li>`).join('');
  return `
    <section class="block" id="deroule">
      <h2>${escapeHtml(section.title)}</h2>
      <ol class="steps">${items}</ol>
    </section>`;
}

function gallery(images) {
  if (!images.length) return '';
  const figures = images.map((img) => `
    <figure>
      <img src="${escapeHtml(img.src)}" alt="${escapeHtml(img.alt ?? '')}" loading="lazy">
      ${img.caption ? `<figcaption>${escapeHtml(img.caption)}</figcaption>` : ''}
    </figure>`).join('');
  return `<section class="block" id="galerie"><h2>À la carte</h2><div class="gallery">${figures}</div></section>`;
}

function contact(content) {
  const c = content.contact ?? {};
  const rows = [];
  if (c.phone) rows.push(`<a href="tel:${escapeHtml(c.phone.replace(/\s/g, ''))}">${escapeHtml(c.phone)}</a>`);
  if (c.email) rows.push(`<a href="mailto:${escapeHtml(c.email)}">${escapeHtml(c.email)}</a>`);
  if (c.instagram) rows.push(`<a href="https://instagram.com/${escapeHtml(c.instagram.replace('@', ''))}" rel="noopener">Instagram</a>`);
  if (!rows.length) return '';
  return `<section class="block" id="contact"><h2>Me joindre</h2><p class="contact">${rows.join(' · ')}</p></section>`;
}

export function renderSite(content) {
  const area = content.area
    ? `<p class="area">Je me déplace : ${escapeHtml(content.area)}</p>` : '';
  const sections = (content.sections ?? []).map(steps).join('');
  const formulas = (content.formulas ?? []).map(formulaCard).join('');
  const about = content.about
    ? `<section class="block" id="apropos"><h2>Qui je suis</h2><p class="about">${escapeHtml(content.about)}</p></section>` : '';

  return `
    <header class="hero">
      <p class="eyebrow">Chef à domicile</p>
      <h1>${escapeHtml(content.name)}</h1>
      <p class="tagline">${escapeHtml(content.tagline)}</p>
      ${content.intro ? `<p class="intro">${escapeHtml(content.intro)}</p>` : ''}
      ${area}
      <a class="cta" href="#reserver">Voir les dates disponibles</a>
    </header>
    ${sections}
    ${formulas ? `<section class="block" id="formules"><h2>Les formules</h2><div class="formulas">${formulas}</div></section>` : ''}
    ${gallery(content.gallery ?? [])}
    ${about}
    <section class="block" id="reserver"><h2>Réserver une date</h2><div id="booking"></div></section>
    ${contact(content)}`;
}
