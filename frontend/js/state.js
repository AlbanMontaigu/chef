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
  submitting: false,
  error: '',
  confirmation: null,   // {ref, date, service, mail_sent}
  loadError: '',
};

export const EMPTY_FORM = { name: '', email: '', phone: '', address: '', city: '', guests: '', formula: '', message: '' };

export function slotsByDate() {
  const map = new Map();
  for (const slot of [...state.slots].sort((a, b) => a.date.localeCompare(b.date))) {
    if (!map.has(slot.date)) map.set(slot.date, []);
    map.get(slot.date).push(slot);
  }
  return map;
}
