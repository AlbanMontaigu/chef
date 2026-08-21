# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

The website of a **chef à domicile** (private chef): a public showcase page and
a **booking system** where the chef opens dates from a back-office and clients
book one directly. Same shape as the `flip7` app it is modelled on: a
**FastAPI + SQLite backend** (`backend/`) and a **vanilla JS frontend**
(`frontend/`) with no build step, deployed as a single Docker image on Coolify.

- Target device: a phone. Most visitors arrive from a link or a QR code.
- UI language: **French**. Code identifiers, comments and docs: **English**.
- Persistence: SQLite (`backend/data/chef.db`), owned by the backend.

## Hard constraints

1. **No build step on the frontend.** `frontend/` is plain HTML/CSS/JS loaded
   via native ES modules. No bundler, no `npm`, no transpiler, no frontend
   framework. Rendering is `state → render() → innerHTML`.
2. **Minimal backend dependencies.** `fastapi` + `uvicorn`, and stdlib for the
   rest — `sqlite3` for storage, `smtplib` for mail, `hmac` for the session
   cookie. No ORM, no mail SDK, no session library.
3. **No external network calls from the page.** No analytics, no CDN, no web
   font, no third-party API. Everything is served from the same origin. The
   design therefore leans on system font stacks — that is a reliability
   constraint, not an oversight, and adding a `@font-face` from a CDN to
   "improve" the look would break it.
4. **Single process, single container.** One FastAPI app serves `/api/*` and
   the static frontend — same origin, no CORS.
5. **All user-facing strings stay in French**, formal `vous` on the public
   site (a client, not a friend), informal `tu` in the back-office (the chef).
6. **Escape every user-supplied string** interpolated into HTML with
   `escapeHtml()` (`frontend/js/util.js`). Names, addresses and messages are
   free text and are rendered in the back-office — never interpolate one raw.

## These are real bookings — the rules that follow from that

- **The database must be on a mounted volume.** `backend/data/` in the
  container. Without it, a redeploy silently erases every booking. This is the
  single most damaging mistake available in this repo.
- **Double-booking is prevented in SQLite, not in Python.** The partial unique
  index `bookings_one_live_per_slot` (`backend/schema.sql`) is what actually
  guarantees one live booking per slot. The check in `create_booking` is there
  for the error message; do not delete the index believing the check covers it.
- **Nothing about mail is allowed to be silent.** Every send outcome is written
  onto the booking row (`mail_client`, `mail_chef`, `mail_error`) and shown in
  the back-office. The client's confirmation is sent **inline, before the HTTP
  response**, precisely so the confirmation page can state what really
  happened — moving it to a background task would make that page lie. The
  chef's copy is the one that goes to the background.
- **A failed mail never rolls back a booking.** The date is blocked either
  way; the client is told the mail did not leave and the chef sees the failure.
- **Cancelling is the only way to free a booked slot.** `DELETE /slots/{id}`
  refuses a booked slot on purpose: deleting it would cascade the booking away
  without telling the client. Cancel first — that mails them.

## Two calendars, on purpose

The visitor gets a **list of open dates** grouped by month; the chef gets a
**month grid** with multi-select. They answer different questions ("when can
I?" versus "which dates do I open?"), and a sparse month grid reads as an empty
diary to a visitor. Don't unify them into one component.

Bulk actions must report what they did *not* do — "4 ouverts, 2 l'étaient déjà",
"3 fermés, 1 réservé laissé en place". A bulk action that silently absorbs the
difference lets the chef believe a date is closed when it is not.

## Content lives in `content/site.json` — except the prices

Texte « à propos », zone d'intervention, sections, galerie, bornes de
réservation (`min_guests`, `max_guests`, `lead_days`), and the `legal` block
that feeds the invoice header. Rewording the site is a JSON edit and a push,
never a code change. A malformed file falls back to neutral defaults and logs
an error rather than taking the booking flow down.

**Formulas and their prices are NOT here — they are rows in `formulas`,
managed from the back-office.** They moved the day they started backing an
invoice: `"à partir de XX €"` is a sentence, not a price, and nothing can be
computed from it. The public site reads them through `/api/content`, which
assembles the JSON and the table into one document so that the price shown to
a visitor is exactly the one the invoice will be built on. Do not re-add a
`formulas` key to the JSON — two sources for one price is how a client gets
quoted one figure and billed another.

`lead_days` is the runway the chef needs for shopping and prep: slots closer
than that are filtered out of the public calendar. The back-office flags such
a slot as "ouvert mais trop proche" instead of showing a green "Ouvert" that
nobody can book.

## Where a private setting goes

`backend/settings.py`, i.e. rows in `meta`, read only by the back-office.
`content/site.json` is committed to a **public** repo and `/api/content` is
served to every visitor, so neither can hold anything private. The chef's
departure address is the current example: it is most likely his home, it never
appears on the site or on an invoice, and he must be able to change it himself
without a redeploy.

Adding a setting means one entry in `DEFAULTS` and one field in the Réglages
tab. Anything the chef would have to open a ticket to change belongs here
rather than in an environment variable — env vars are for what an operator
sets once (`SMTP_HOST`, `INVOICE_IBAN`), settings are for what the chef
changes.

## The travel estimate, and why it refuses so much

`backend/travel.py` calls two public demo servers (Nominatim, then OSRM) from
the **server**, never from the page, and only on an explicit back-office click.
No dependency was added — `urllib` is enough.

The rule that matters: **a confident wrong answer is worse than no answer.**
This is not theoretical. In testing, "Salle des fêtes" with no city geocoded to
a village 756 km away and the app reported "7 h 49" without hesitating. Two
guards followed, and neither should be relaxed to make the feature "work more
often":

- No postcode/city on the booking → refuse **before** any network call. A
  street without a town is ambiguous nationwide, and the geocoder guesses
  rather than failing.
- Distance over `TRAVEL_MAX_KM` → discard the result and report the address
  *as it was located*, so the chef can see where it went wrong.

Every refusal is stored and displayed with its reason: an address the chef can
fix must be distinguishable from a service to retry. Results are cached (on the
booking, and geocodes in `geocache`) because these services ask for it and
because an address does not move.

## Money, formulas and invoices

- **Every amount is an integer of cents**, front and back (`backend/money.py`,
  `formatAmount`/`parseAmount` in `frontend/js/util.js`). No float ever touches
  a price. Conversion to decimal happens at display and at input parsing, and
  nowhere else.
- **What is paid is the sum of the `payments` rows.** There is deliberately no
  "paid" column to keep in step with them: a derived total cannot drift. A
  refund is a negative row, so the sum stays the balance. The sign comes from
  the *kind*, never from what the chef typed.
- **A draft invoice is editable; an issued one is frozen.** The number is
  allocated at issue, inside the transaction that freezes the totals, and the
  sequence has no holes. Correcting an issued invoice means cancelling it —
  with a reason, which is required — and issuing the next one. Never rewrite a
  document that already left. `invoices_one_live_per_booking` enforces at most
  one non-cancelled invoice per booking.
- **Identities are copied onto the invoice at issue** (`seller_json`,
  `client_json`). The chef's SIRET or the client's address will change; an
  invoice already sent must not change with them.
- **A balance only exists once a bill has been issued.** A draft is an
  intention, not a debt: showing it as an outstanding amount would send the
  chef chasing a client who never received anything. Before that, the
  back-office shows an *estimate* and says so.
- **The VAT regime is not guessable from the code.** `VAT_RATE_BP` defaults to
  0, which prints the franchise mention instead of a VAT line. Confirm the
  chef's actual status before the first real invoice; do not infer it.
- Invoices render as a printable HTML page (`backend/invoice_html.py`), served
  by `/api/admin/invoices/{id}/view` and attached to the client's e-mail. One
  renderer, so what the chef proof-reads is byte-for-byte what the client
  gets. No PDF library — the dependency constraint holds, and the browser
  prints to PDF.

## The demo seed, and keeping it honest

`backend/seed.py` fills an empty database with a set of examples that make the
back-office readable: formulas, open slots, bookings in every state, payments,
a paid invoice, a partly-paid one, a draft, and one cancelled-then-reissued.

- The seller identity printed on demo invoices is fictitious and lives in
  `seed.DEMO_LEGAL` (used only while `SEED_DEMO` is on). Without it every demo
  invoice prints the `PLACEHOLDER` strings and shows nothing.
- It only ever touches rows it created (`demo = 1`), so it cannot delete a
  real booking. `SEED_DEMO` gates it — on in `DEV`, off elsewhere — and
  turning it off removes the examples on the next start.
- It steps aside for reality: as soon as one non-demo booking exists, the
  examples are removed and never replayed. A demo invoice indistinguishable
  from a real one is worse than an empty back-office.
- `SEED_VERSION` is a single global integer. Bump it and the next start
  replays the set.

**`tools/check-seed.py` is what makes that rule enforceable.** It seeds a
throwaway database and asserts that every state the interface can display is
actually represented — 42 of them today, from "formula priced per guest with
no amount entered" to "invoice overdue and unpaid". Run it after any change to
the domain:

```sh
.venv/bin/python tools/check-seed.py
```

It names exactly what is missing and exits 1. Adding a state to the code means
adding a line there **and** an example in `backend/seed.py`, in the same
commit.

> **Standing rule — never let the example data fall behind the features.**
> Any change that adds a field, a state, or a flow must show up in
> `backend/seed.py` in the same commit, `SEED_VERSION` must be bumped, and
> `tools/check-seed.py` must cover it.
> A seed that only covers the nominal case leaves half the interface
> unexercised, and the first time anyone sees the new state rendered is in
> production, on a real booking. The examples are the cheapest test surface
> this repo has; they are only worth something while they still describe what
> the code does.

## Configuration is entirely environment-driven

`backend/config.py` holds no domain, address or secret. The site starts on
`chef.montaigu.org` and is expected to move to the chef's own domain: that
move must be a change of environment variables in Coolify, not a code change.
See `docs/deployment.md`.

Two variables have no safe default and are shouted at startup when missing:
`ADMIN_PASSWORD` (without it the back-office refuses every login — an unset
password must never mean "no password") and `SMTP_HOST` (without it no
confirmation is ever sent).

## Where the backend is authoritative

- Availability: `GET /api/availability` is the only truth about what is
  bookable. The frontend never decides a date is free.
- Slot ownership: only the back-office creates or closes slots.
- The `ref` given to the client (`R-XXXXXX`) is generated server-side from an
  alphabet with no look-alike characters, so it can be read over the phone.
