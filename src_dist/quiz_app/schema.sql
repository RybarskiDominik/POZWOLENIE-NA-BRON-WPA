CREATE TABLE sheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    question_count INTEGER DEFAULT 20 CHECK (question_count > 0),
    shuffle_answers INTEGER NOT NULL DEFAULT 1 CHECK (shuffle_answers IN (0, 1)),
    mode TEXT NOT NULL DEFAULT 'quiz' CHECK (mode IN ('quiz', 'test')),
    selected_set_id INTEGER REFERENCES question_sets(id) ON DELETE SET NULL,
    last_session_id TEXT REFERENCES quiz_sessions(id) ON DELETE SET NULL
);
CREATE TABLE questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sheet_id INTEGER NOT NULL REFERENCES sheets(id) ON DELETE CASCADE,
    number INTEGER NOT NULL CHECK (number > 0),
    text TEXT NOT NULL,
    legal_basis TEXT NOT NULL DEFAULT '',
    explanation TEXT NOT NULL DEFAULT '',
    is_problem INTEGER NOT NULL DEFAULT 0 CHECK (is_problem IN (0, 1)),
    is_difficult INTEGER NOT NULL DEFAULT 0 CHECK (is_difficult IN (0, 1)),
    UNIQUE (sheet_id, number),
    UNIQUE (id, sheet_id)
);
CREATE TABLE answers (
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    label TEXT NOT NULL,
    text TEXT NOT NULL,
    is_correct INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
    PRIMARY KEY (question_id, position)
);
CREATE TABLE question_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sheet_id INTEGER NOT NULL REFERENCES sheets(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'custom' CHECK (kind IN ('all', 'problems', 'problems_keep', 'difficult', 'custom')),
    UNIQUE (id, sheet_id)
);
CREATE INDEX sets_by_sheet ON question_sets(sheet_id, name);
CREATE UNIQUE INDEX default_set_per_sheet ON question_sets(sheet_id, kind) WHERE kind != 'custom';
CREATE TABLE set_questions (
    set_id INTEGER NOT NULL,
    sheet_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    PRIMARY KEY (set_id, question_id),
    UNIQUE (set_id, position),
    FOREIGN KEY (set_id, sheet_id) REFERENCES question_sets(id, sheet_id) ON DELETE CASCADE,
    FOREIGN KEY (question_id, sheet_id) REFERENCES questions(id, sheet_id) ON DELETE CASCADE
);
CREATE INDEX sets_by_question ON set_questions(question_id);
CREATE TABLE quiz_sessions (
    id TEXT PRIMARY KEY,
    sheet_id INTEGER NOT NULL REFERENCES sheets(id) ON DELETE CASCADE,
    set_id INTEGER REFERENCES question_sets(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('quiz', 'test')),
    status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'cancelled')),
    position INTEGER NOT NULL CHECK (position >= 0),
    elapsed_seconds REAL NOT NULL CHECK (elapsed_seconds >= 0 AND elapsed_seconds <= 1.7976931348623157e308),
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE UNIQUE INDEX one_active_session_per_sheet ON quiz_sessions(sheet_id) WHERE status = 'active';
CREATE TABLE session_items (
    session_id TEXT NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    question_json TEXT NOT NULL,
    selected_index INTEGER CHECK (selected_index >= 0),
    confirmed INTEGER NOT NULL CHECK (confirmed IN (0, 1)),
    is_correct INTEGER CHECK (is_correct IN (0, 1)),
    elapsed_seconds REAL NOT NULL CHECK (elapsed_seconds >= 0 AND elapsed_seconds <= 1.7976931348623157e308),
    answered_at TEXT,
    PRIMARY KEY (session_id, position)
);
CREATE INDEX attempts_by_question ON session_items(question_id);
CREATE TABLE question_progress (
    sheet_id INTEGER NOT NULL REFERENCES sheets(id) ON DELETE CASCADE,
    set_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    PRIMARY KEY (set_id, question_id),
    FOREIGN KEY (set_id, sheet_id) REFERENCES question_sets(id, sheet_id) ON DELETE CASCADE,
    FOREIGN KEY (question_id, sheet_id) REFERENCES questions(id, sheet_id) ON DELETE CASCADE
);
CREATE TABLE answer_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sheet_id INTEGER NOT NULL REFERENCES sheets(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    is_correct INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
    elapsed_seconds REAL NOT NULL CHECK (elapsed_seconds >= 0 AND elapsed_seconds <= 1.7976931348623157e308),
    answered_at TEXT NOT NULL,
    UNIQUE (session_id, position),
    FOREIGN KEY (question_id, sheet_id) REFERENCES questions(id, sheet_id) ON DELETE CASCADE
);
CREATE INDEX history_by_sheet ON answer_history(sheet_id, id);
CREATE TABLE app_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    sheet_id INTEGER REFERENCES sheets(id) ON DELETE SET NULL
);
INSERT INTO app_state(id) VALUES (1);
