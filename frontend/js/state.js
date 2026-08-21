// Objet d'état unique, mutable : state → render() → DOM.
export const state = {
  content: null,
  slots: [],            // [{id, date, service, note}] — uniquement les créneaux libres
  selectedDate: null,   // YYYY-MM-DD choisi dans la liste
  selectedSlot: null,   // le créneau retenu (date + service)
  // `diets` est une Map id -> nombre de convives concernés. Pas un tableau de
  // booléens : « deux végétariens » et « des végétariens » ne se cuisinent pas
  // pareil. Hors de `form`, qui est capturé champ par champ depuis le DOM.
  form: { name: '', email: '', phone: '', address: '', city: '', guests: '', formula: '', message: '' },
  diets: new Map(),
  quoteForm: { name: '', email: '', phone: '', city: '', wanted_date: '',
               service: '', flexibility: '', guests: '', occasion: '', formula: '', message: '' },
  quoteDiets: new Set(),
  quoteSubmitting: false,
  quoteError: '',
  quoteConfirmation: null,
  submitting: false,
  error: '',
  confirmation: null,   // {ref, date, service, mail_sent}
  loadError: '',
};

// Demande de devis : un état parallèle à celui de la réservation, pas une
// variante du même. Les deux formulaires cohabitent sur la page, et une saisie
// commencée dans l'un ne doit jamais se retrouver dans l'autre.
export const EMPTY_QUOTE = { name: '', email: '', phone: '', city: '', wanted_date: '',
  service: '', flexibility: '', guests: '', occasion: '', formula: '', message: '' };

export const EMPTY_FORM = { name: '', email: '', phone: '', address: '', city: '', guests: '', formula: '', message: '' };

export function slotsByDate() {
  const map = new Map();
  for (const slot of [...state.slots].sort((a, b) => a.date.localeCompare(b.date))) {
    if (!map.has(slot.date)) map.set(slot.date, []);
    map.get(slot.date).push(slot);
  }
  return map;
}
