-- A slot is one service the chef is willing to cook: a date + midi/soir.
-- The chef opens them from the back-office; the public site only ever sees
-- the ones still available.
CREATE TABLE IF NOT EXISTS slots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,              -- YYYY-MM-DD, Europe/Paris
    service     TEXT NOT NULL,              -- 'midi' | 'soir'
    note        TEXT NOT NULL DEFAULT '',   -- optional, shown to visitors
    created_at  TEXT NOT NULL,
    demo        INTEGER NOT NULL DEFAULT 0, -- 1 = posé par le jeu de démonstration
    UNIQUE (date, service)
);

CREATE TABLE IF NOT EXISTS bookings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ref           TEXT NOT NULL UNIQUE,     -- human-readable, given to the client
    -- Secret d'accès à la page de suivi du client. SÉPARÉ de `ref` à dessein :
    -- la référence est faite pour être lue au téléphone (alphabet sans
    -- sosies, six caractères), donc devinable ; elle ne peut pas servir de
    -- clé d'URL. Le jeton est long, aléatoire, et n'est jamais affiché.
    token         TEXT,
    slot_id       INTEGER NOT NULL REFERENCES slots(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL,
    phone         TEXT NOT NULL DEFAULT '',
    address       TEXT NOT NULL DEFAULT '',
    -- Séparé de la rue : sans code postal ni ville, un géocodeur ne peut pas
    -- distinguer deux rues homonymes, et une durée de trajet fausse est pire
    -- qu'une durée absente.
    city          TEXT NOT NULL DEFAULT '',
    guests        INTEGER NOT NULL,
    -- Libellé de la formule figé au moment de la réservation : la formule
    -- peut être renommée ou retirée ensuite, ce que le client a choisi ce
    -- jour-là ne doit pas bouger avec elle.
    formula       TEXT NOT NULL DEFAULT '',
    formula_id    INTEGER REFERENCES formulas(id) ON DELETE SET NULL,
    message       TEXT NOT NULL DEFAULT '',
    -- Régimes et allergies déclarés : JSON [{"id": "sans-gluten", "count": 2}].
    -- Sortis du message libre à dessein : une allergie noyée dans un
    -- paragraphe se lit le jour du repas, ou pas du tout. Le nombre compte
    -- autant que la nature -- cf. backend/diets.py.
    diets         TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'confirmed',   -- 'confirmed' | 'cancelled'
    created_at    TEXT NOT NULL,
    cancelled_at  TEXT,
    -- Mail outcome, per recipient. 'pending' until the send is attempted,
    -- then 'sent' | 'failed' | 'disabled'. Never silently dropped.
    mail_client   TEXT NOT NULL DEFAULT 'pending',
    mail_chef     TEXT NOT NULL DEFAULT 'pending',
    mail_error    TEXT NOT NULL DEFAULT '',
    -- 1 = posée par le jeu de démonstration. Porté par la réservation et non
    -- déduit du créneau : un vrai client qui réserverait un créneau semé par
    -- erreur serait sinon effacé avec les exemples.
    demo          INTEGER NOT NULL DEFAULT 0,
    -- Estimation de trajet, calculée à la demande depuis le back-office et
    -- conservée ici : les services interrogés sont publics et sans garantie,
    -- on ne les rappelle donc pas à chaque affichage. `travel_error` retient
    -- le motif d'un échec, pour l'afficher au lieu d'un blanc.
    travel_seconds INTEGER,
    travel_meters  INTEGER,
    travel_error   TEXT NOT NULL DEFAULT '',
    -- Adresse telle que le géocodeur l'a comprise. Affichée au chef : c'est le
    -- seul moyen qu'il repère qu'une adresse approximative a été mal placée.
    travel_label   TEXT NOT NULL DEFAULT '',
    -- 1 = estimé depuis le centre de la commune, l'adresse exacte étant
    -- introuvable. Affiché comme tel, jamais confondu avec une estimation
    -- porte-à-porte.
    travel_approx  INTEGER NOT NULL DEFAULT 0,
    travel_at      TEXT
);

-- Double-booking protection at the storage layer, not in application logic:
-- a slot can carry at most one live booking, whatever races upstream.
CREATE UNIQUE INDEX IF NOT EXISTS bookings_one_live_per_slot
    ON bookings (slot_id) WHERE status = 'confirmed';

-- Le jeton est une clé d'accès : deux réservations ne peuvent pas partager la
-- même, sous peine de montrer à un client le dossier d'un autre. Les valeurs
-- NULL restent distinctes en SQLite, ce qui laisse passer une base ancienne le
-- temps que la migration remplisse la colonne.
CREATE UNIQUE INDEX IF NOT EXISTS bookings_by_token ON bookings (token);

CREATE INDEX IF NOT EXISTS bookings_by_created ON bookings (created_at DESC);
CREATE INDEX IF NOT EXISTS slots_by_date ON slots (date);

-- --------------------------------------------------------------------
-- Clé/valeur interne. Sert aujourd'hui au versionnement du jeu de
-- démonstration ; c'est le seul endroit où le backend garde un état qui
-- n'est ni un créneau, ni une réservation, ni une facture.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- --------------------------------------------------------------------
-- Formules et tarifs. Elles vivaient dans content/site.json tant qu'elles
-- n'étaient que du texte ; à partir du moment où un tarif sert de base à une
-- facture, il lui faut un montant en centimes et une identité stable dans la
-- base. Le site public lit cette table, l'éditorial reste dans le JSON.
CREATE TABLE IF NOT EXISTS formulas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT NOT NULL UNIQUE,       -- stable, cité par les réservations
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    pricing      TEXT NOT NULL DEFAULT 'per_guest',  -- 'per_guest' | 'fixed' | 'quote'
    price_cents  INTEGER NOT NULL DEFAULT 0, -- entier, jamais un flottant
    min_guests   INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1, -- 0 = retirée du site, conservée pour l'historique
    position     INTEGER NOT NULL DEFAULT 0,
    demo         INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

-- --------------------------------------------------------------------
-- Encaissements. Le solde d'une réservation est TOUJOURS la somme de ces
-- lignes -- il n'existe volontairement aucune colonne « payé » à maintenir
-- en parallèle, qui finirait par mentir. Un remboursement est une ligne de
-- montant négatif, pour que la somme reste le solde.
CREATE TABLE IF NOT EXISTS payments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id   INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL DEFAULT 'acompte',   -- 'acompte' | 'solde' | 'remboursement'
    amount_cents INTEGER NOT NULL,
    method       TEXT NOT NULL DEFAULT 'virement',  -- virement | especes | cheque | cb | autre
    received_on  TEXT NOT NULL,                     -- YYYY-MM-DD
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS payments_by_booking ON payments (booking_id);

-- --------------------------------------------------------------------
-- Factures. Un brouillon s'édite librement ; une facture émise est figée --
-- numéro attribué, totaux gelés, lignes verrouillées. Corriger une facture
-- émise se fait en l'annulant et en en émettant une autre, jamais en la
-- réécrivant : c'est ce que demande une numérotation séquentielle sans trou.
CREATE TABLE IF NOT EXISTS invoices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id   INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    number       TEXT UNIQUE,                     -- NULL tant que brouillon
    status       TEXT NOT NULL DEFAULT 'draft',   -- 'draft' | 'issued' | 'cancelled'
    issued_on    TEXT,                            -- date de facture, YYYY-MM-DD
    due_on       TEXT,
    vat_rate_bp  INTEGER NOT NULL DEFAULT 0,      -- points de base ; 0 = non applicable
    vat_note     TEXT NOT NULL DEFAULT '',
    -- Identités recopiées à l'émission : le statut du chef ou l'adresse du
    -- client changeront, une facture émise ne doit pas changer avec eux.
    seller_json  TEXT NOT NULL DEFAULT '{}',
    client_json  TEXT NOT NULL DEFAULT '{}',
    notes        TEXT NOT NULL DEFAULT '',
    total_cents  INTEGER NOT NULL DEFAULT 0,      -- gelé à l'émission
    created_at   TEXT NOT NULL,
    issued_at    TEXT,
    cancelled_at TEXT,
    cancel_reason TEXT NOT NULL DEFAULT '',
    mail_status  TEXT NOT NULL DEFAULT 'pending', -- 'pending'|'sent'|'failed'|'disabled'
    mail_error   TEXT NOT NULL DEFAULT '',
    mail_sent_at TEXT
);

-- Au plus une facture vivante par réservation : une facture annulée laisse la
-- place à la suivante, deux factures actives pour un même repas n'en laissent
-- aucune faisant foi.
CREATE UNIQUE INDEX IF NOT EXISTS invoices_one_live_per_booking
    ON invoices (booking_id) WHERE status <> 'cancelled';

CREATE INDEX IF NOT EXISTS invoices_by_status ON invoices (status, issued_on);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id  INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 1,
    unit_cents  INTEGER NOT NULL DEFAULT 0,
    position    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS invoice_lines_by_invoice ON invoice_lines (invoice_id, position);


-- --------------------------------------------------------------------
-- Adresses déjà géocodées. Le service de géocodage utilisé demande
-- explicitement que les résultats soient mis en cache plutôt que redemandés :
-- cette table est cette mise en cache. Une adresse ne bouge pas.
CREATE TABLE IF NOT EXISTS geocache (
    query      TEXT PRIMARY KEY,
    lat        REAL,
    lon        REAL,
    label      TEXT NOT NULL DEFAULT '',   -- adresse telle que reconnue, pour vérification
    created_at TEXT NOT NULL
);

-- --------------------------------------------------------------------
-- Rappels et relances. Une ligne = un envoi prévu, à une date donnée, pour
-- une cible donnée. Elle est inscrite d'abord, envoyée ensuite : c'est cette
-- séparation qui rend le « une seule fois » vérifiable -- il est porté par
-- l'index unique ci-dessous, et par rien d'autre. Cf. backend/reminders.py.
CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,     -- 'repas_proche' | 'facture_echue' | 'a_facturer'
    -- 'booking:12' / 'invoice:7'. Une chaîne plutôt que deux colonnes
    -- nullables : en SQLite deux NULL sont distincts, un index unique portant
    -- sur une colonne vide ne dédoublonnerait donc rien.
    target     TEXT NOT NULL,
    due_on     TEXT NOT NULL,     -- date à laquelle l'envoi devient dû
    status     TEXT NOT NULL DEFAULT 'pending',  -- pending|sent|failed|skipped
    recipient  TEXT NOT NULL DEFAULT '',
    attempts   INTEGER NOT NULL DEFAULT 0,
    -- Motif d'abandon ('skipped') ou dernière erreur d'envoi. Jamais vidé :
    -- un rappel qui n'est pas parti doit dire pourquoi, même des mois après.
    error      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    sent_at    TEXT,
    -- 1 = posé par le jeu de démonstration. Même règle que partout ailleurs :
    -- la purge ne vise que ce marqueur, et ne peut donc pas effacer la trace
    -- d'une relance réellement envoyée à un vrai client.
    demo       INTEGER NOT NULL DEFAULT 0
);

-- Le « une seule fois » vit ici. Deux relances d'une même facture existent en
-- portant deux échéances différentes ; la même échéance ne s'inscrit qu'une
-- fois, quel que soit le nombre de replanifications.
CREATE UNIQUE INDEX IF NOT EXISTS reminders_once ON reminders (kind, target, due_on);
CREATE INDEX IF NOT EXISTS reminders_due ON reminders (status, due_on);

-- --------------------------------------------------------------------
-- Demandes de devis. Le calendrier ne montre que les créneaux que le chef a
-- ouverts ; tout ce qui n'y entre pas -- une date non ouverte, un mariage, un
-- buffet de quarante personnes -- n'avait aucun chemin et se perdait. Une
-- demande de devis n'est PAS une réservation : elle ne prend aucun créneau,
-- ne bloque aucune date, et n'a donc pas d'index d'unicité à défendre.
CREATE TABLE IF NOT EXISTS quotes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ref          TEXT NOT NULL UNIQUE,        -- Q-XXXXXX, lisible au téléphone
    name         TEXT NOT NULL,
    email        TEXT NOT NULL,
    phone        TEXT NOT NULL DEFAULT '',
    city         TEXT NOT NULL DEFAULT '',
    -- Date souhaitée, quand il y en a une. Souvent absente : « un samedi de
    -- juin » est une demande parfaitement normale, et la refuser faute de
    -- date exacte ferait perdre la demande.
    wanted_date  TEXT NOT NULL DEFAULT '',
    service      TEXT NOT NULL DEFAULT '',    -- 'midi' | 'soir' | '' (peu importe)
    flexibility  TEXT NOT NULL DEFAULT '',    -- « plutôt fin juin », « un week-end »
    guests       INTEGER NOT NULL DEFAULT 0,
    occasion     TEXT NOT NULL DEFAULT '',
    formula      TEXT NOT NULL DEFAULT '',    -- libellé figé, comme sur une réservation
    formula_id   INTEGER REFERENCES formulas(id) ON DELETE SET NULL,
    diets        TEXT NOT NULL DEFAULT '[]',
    message      TEXT NOT NULL DEFAULT '',
    -- 'new' -> le chef n'a rien fait ; 'answered' -> il a répondu ;
    -- 'converted' -> c'est devenu une réservation ; 'declined' -> refusée.
    -- Aucune transition n'est automatique : c'est le chef qui sait.
    status       TEXT NOT NULL DEFAULT 'new',
    note         TEXT NOT NULL DEFAULT '',    -- interne, jamais montré au client
    created_at   TEXT NOT NULL,
    answered_at  TEXT,
    mail_client  TEXT NOT NULL DEFAULT 'pending',
    mail_chef    TEXT NOT NULL DEFAULT 'pending',
    mail_error   TEXT NOT NULL DEFAULT '',
    demo         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS quotes_by_status ON quotes (status, created_at DESC);
