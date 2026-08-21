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

## Content lives in `content/site.json`

Prestations, tarifs, texte « à propos », zone d'intervention, bornes de
réservation (`min_guests`, `max_guests`, `lead_days`). Rewording the site is a
JSON edit and a push, never a code change. A malformed file falls back to
neutral defaults and logs an error rather than taking the booking flow down.

`lead_days` is the runway the chef needs for shopping and prep: slots closer
than that are filtered out of the public calendar. The back-office flags such
a slot as "ouvert mais trop proche" instead of showing a green "Ouvert" that
nobody can book.

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
