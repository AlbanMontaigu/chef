import { escapeHtml } from '../util.js';

function photo(src, alt, fallbackLetter) {
  if (src) return `<img class="round" src="${escapeHtml(src)}" alt="${escapeHtml(alt)}">`;
  // Pas de photo fournie : un disque texturé tient la place. Une balise <img>
  // sans source afficherait une image cassée, ce qui est pire que rien.
  return `<div class="round round-placeholder" role="img" aria-label="${escapeHtml(alt)}">${escapeHtml(fallbackLetter)}</div>`;
}

function topbar(content) {
  const links = [
    content.sections?.length ? '<a href="#deroule">Comment ça marche</a>' : '',
    content.formulas?.length ? '<a href="#formules">Formules</a>' : '',
    content.about ? '<a href="#apropos">Le chef</a>' : '',
  ].filter(Boolean).join('');
  return `
    <div class="topbar">
      <div class="wrap">
        <a class="brand" href="#top">${escapeHtml(content.name)}</a>
        <nav class="topnav">${links}<a class="btn-nav" href="#reserver">Réserver</a></nav>
      </div>
    </div>`;
}

function hero(content) {
  const initial = (content.name || 'C').trim().charAt(0).toUpperCase();
  return `
    <header class="hero" id="top">
      <div class="wrap hero-grid">
        <div>
          <p class="eyebrow">Chef à domicile</p>
          <h1>${escapeHtml(content.name)}</h1>
          <p class="tagline">${escapeHtml(content.tagline)}</p>
          ${content.intro ? `<p class="intro">${escapeHtml(content.intro)}</p>` : ''}
          ${content.area ? `<p class="area">${escapeHtml(content.area)}</p>` : ''}
          <div class="hero-actions">
            <a class="cta" href="#reserver">Voir les dates disponibles</a>
            ${content.formulas?.length ? '<a class="cta-ghost" href="#formules">Découvrir les formules</a>' : ''}
          </div>
        </div>
        <div class="hero-photo">${photo(content.hero_photo, `Un plat de ${content.name}`, initial)}</div>
      </div>
    </header>`;
}

function steps(section) {
  const items = (section.steps ?? []).map((s) => `<li>${escapeHtml(s)}</li>`).join('');
  return `
    <section class="block tinted" id="deroule">
      <div class="wrap">
        <h2>${escapeHtml(section.title)}</h2>
        <p class="lede">Quatre étapes, et vous ne touchez ni aux courses ni à la vaisselle.</p>
        <ol class="steps">${items}</ol>
      </div>
    </section>`;
}

function formulas(list) {
  if (!list.length) return '';
  const cards = list.map((f) => `
    <article class="formula">
      <h3>${escapeHtml(f.name)}</h3>
      <p class="formula-desc">${escapeHtml(f.description)}</p>
      <p class="formula-price">${escapeHtml(f.price)}</p>
      ${f.min_guests ? `<p class="formula-min">dès ${escapeHtml(f.min_guests)} convives</p>` : ''}
    </article>`).join('');
  return `
    <section class="block" id="formules">
      <div class="wrap">
        <h2>Les formules</h2>
        <p class="lede">Le menu se cale ensemble, selon la saison et vos envies. Ces formules donnent le cadre.</p>
        <div class="formulas">${cards}</div>
      </div>
    </section>`;
}

function gallery(images) {
  if (!images.length) return '';
  const figures = images.map((img) => `
    <figure>
      <img src="${escapeHtml(img.src)}" alt="${escapeHtml(img.alt ?? '')}" loading="lazy">
      ${img.caption ? `<figcaption>${escapeHtml(img.caption)}</figcaption>` : ''}
    </figure>`).join('');
  return `
    <section class="block tinted" id="galerie">
      <div class="wrap"><h2>Quelques assiettes</h2><div class="gallery">${figures}</div></div>
    </section>`;
}

function about(content) {
  if (!content.about) return '';
  const initial = (content.name || 'C').trim().charAt(0).toUpperCase();
  return `
    <section class="block" id="apropos">
      <div class="wrap about-grid">
        <div class="about-photo">${photo(content.portrait, `Portrait de ${content.name}`, initial)}</div>
        <div>
          <h2>Qui vient cuisiner</h2>
          <p class="about">${escapeHtml(content.about)}</p>
        </div>
      </div>
    </section>`;
}

function footer(content) {
  const c = content.contact ?? {};
  const links = [];
  if (c.phone) links.push(`<a href="tel:${escapeHtml(c.phone.replace(/\s/g, ''))}">${escapeHtml(c.phone)}</a>`);
  if (c.email) links.push(`<a href="mailto:${escapeHtml(c.email)}">${escapeHtml(c.email)}</a>`);
  if (c.instagram) links.push(`<a href="https://instagram.com/${escapeHtml(c.instagram.replace('@', ''))}" rel="noopener">Instagram</a>`);
  const legal = content.legal ?? {};
  const legalLine = [legal.status, legal.siret ? `SIRET ${legal.siret}` : ''].filter(Boolean).join(' · ');
  return `
    <footer class="site-footer" id="contact">
      <div class="wrap">
        <div class="footer-grid">
          <div>
            <h2 style="font-size:1.4rem;margin-bottom:0.5rem">Une question ?</h2>
            ${links.length ? `<p class="contact-list">${links.join('')}</p>`
              : '<p class="notice">Passez par le formulaire de réservation, on se recontacte de là.</p>'}
          </div>
          <div>
            ${legalLine ? `<p class="legal">${escapeHtml(legalLine)}</p>` : ''}
            <p class="build" id="build-stamp"></p>
          </div>
        </div>
      </div>
    </footer>`;
}

export function renderSite(content) {
  const sections = (content.sections ?? []).map(steps).join('');
  return `
    ${topbar(content)}
    ${hero(content)}
    ${sections}
    ${formulas(content.formulas ?? [])}
    ${gallery(content.gallery ?? [])}
    ${about(content)}
    <section class="block tinted" id="reserver">
      <div class="wrap">
        <h2>Réserver une date</h2>
        <p class="lede">Choisissez un créneau libre, laissez vos coordonnées : la date est bloquée immédiatement.</p>
        <div class="booking-shell" id="booking"></div>
      </div>
    </section>
    ${footer(content)}`;
}
