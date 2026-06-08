import csv
import io
import sqlite3
from collections import defaultdict
from datetime import date
from flask import Flask, render_template, request, redirect, url_for, jsonify, Response

app = Flask(__name__)
DATABASE = 'udl_marks_db.sqlite'

MAX_SCORE = 16
DISCREPANCY_THRESHOLD = 3  # peak − avg gap that triggers a review flag

BANDS = [
    (16, 16, 'Beyond Stage',          'band-beyond'),
    (13, 15, 'Well Above Standard',   'band-well-above'),
    (10, 12, 'Above Standard',        'band-above'),
    ( 7,  9, 'At Standard',           'band-standard'),
    ( 4,  6, 'Working Towards',       'band-working'),
    ( 1,  3, 'Limited',               'band-limited'),
]


def _score_band(score):
    """Return (label, css_class) for a score of 0–16. 0 returns (None, 'band-none')."""
    if not score:
        return None, 'band-none'
    for lo, hi, label, css in BANDS:
        if lo <= score <= hi:
            return label, css
    return None, 'band-none'


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS stages (
            stage_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_name TEXT UNIQUE NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS stage_years (
            stage_id   INTEGER NOT NULL,
            year_group TEXT    NOT NULL,
            PRIMARY KEY (stage_id, year_group),
            FOREIGN KEY (stage_id) REFERENCES stages(stage_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id      INTEGER PRIMARY KEY,
            first_name      TEXT NOT NULL,
            last_name       TEXT NOT NULL,
            year_group      TEXT,
            enrollment_date DATE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            subject_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_name TEXT UNIQUE NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS classes (
            class_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            year_group TEXT    NOT NULL,
            stage_id   INTEGER NOT NULL,
            FOREIGN KEY (subject_id) REFERENCES subjects(subject_id),
            FOREIGN KEY (stage_id)   REFERENCES stages(stage_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS outcomes (
            outcome_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            outcome_code  TEXT UNIQUE NOT NULL,
            outcome_name  TEXT NOT NULL,
            is_theoretical BOOLEAN NOT NULL DEFAULT 1,
            subject_id    INTEGER,
            stage_id      INTEGER,
            FOREIGN KEY (subject_id) REFERENCES subjects(subject_id),
            FOREIGN KEY (stage_id)   REFERENCES stages(stage_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS attempts (
            attempt_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id       INTEGER NOT NULL,
            class_id         INTEGER,
            attempt_date     DATE    NOT NULL,
            assessment_title TEXT    NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students(student_id),
            FOREIGN KEY (class_id)   REFERENCES classes(class_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS attempt_outcomes (
            attempt_outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id         INTEGER NOT NULL,
            outcome_id         INTEGER NOT NULL,
            FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id),
            FOREIGN KEY (outcome_id) REFERENCES outcomes(outcome_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS scoring_detail (
            scoring_detail_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_outcome_id INTEGER NOT NULL,
            score              INTEGER NOT NULL,
            FOREIGN KEY (attempt_outcome_id) REFERENCES attempt_outcomes(attempt_outcome_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS student_classes (
            student_id INTEGER NOT NULL,
            class_id   INTEGER NOT NULL,
            PRIMARY KEY (student_id, class_id),
            FOREIGN KEY (student_id) REFERENCES students(student_id),
            FOREIGN KEY (class_id)   REFERENCES classes(class_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS _meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # Migrate existing databases that predate these schema changes
    _migrations = [
        "ALTER TABLE students ADD COLUMN year_group TEXT",
        "ALTER TABLE classes  RENAME COLUMN grade_level TO year_group",
        "ALTER TABLE classes  ADD COLUMN stage_id   INTEGER REFERENCES stages(stage_id)",
        "ALTER TABLE classes  ADD COLUMN class_code TEXT",
        "ALTER TABLE outcomes ADD COLUMN subject_id INTEGER REFERENCES subjects(subject_id)",
        "ALTER TABLE outcomes ADD COLUMN stage_id   INTEGER REFERENCES stages(stage_id)",
        "ALTER TABLE attempts DROP COLUMN class_id",  # will fail gracefully — replaced by nullable below
    ]
    for sql in _migrations:
        try:
            c.execute(sql)
        except Exception:
            pass

    # Remove duplicate classes created by repeated seed_db() calls (keep lowest class_id per group).
    c.execute("PRAGMA foreign_keys = OFF")

    # student_classes has a PK on (student_id, class_id) so we can't UPDATE in place —
    # instead insert canonical rows first (OR IGNORE skips already-existing pairs),
    # then delete the non-canonical rows.
    c.execute("""
        INSERT OR IGNORE INTO student_classes (student_id, class_id)
        SELECT sc.student_id,
               (SELECT MIN(c2.class_id) FROM classes c2
                WHERE c2.subject_id = c1.subject_id
                  AND c2.year_group  = c1.year_group
                  AND COALESCE(c2.class_code,'') = COALESCE(c1.class_code,''))
        FROM student_classes sc
        JOIN classes c1 ON c1.class_id = sc.class_id
        WHERE sc.class_id NOT IN (
            SELECT MIN(class_id) FROM classes GROUP BY subject_id, year_group, COALESCE(class_code,'')
        )
    """)
    c.execute("""
        DELETE FROM student_classes
        WHERE class_id NOT IN (
            SELECT MIN(class_id) FROM classes GROUP BY subject_id, year_group, COALESCE(class_code,'')
        )
    """)

    # Remap attempts to canonical class_id (no PK issue here)
    c.execute("""
        UPDATE attempts
        SET class_id = (
            SELECT MIN(c2.class_id) FROM classes c2
            WHERE c2.subject_id = (SELECT subject_id FROM classes WHERE class_id = attempts.class_id)
              AND c2.year_group  = (SELECT year_group  FROM classes WHERE class_id = attempts.class_id)
              AND COALESCE(c2.class_code,'') =
                  COALESCE((SELECT class_code FROM classes WHERE class_id = attempts.class_id),'')
        )
        WHERE class_id IS NOT NULL
          AND class_id NOT IN (
            SELECT MIN(class_id) FROM classes GROUP BY subject_id, year_group, COALESCE(class_code,'')
        )
    """)

    c.execute("""
        DELETE FROM classes
        WHERE class_id NOT IN (
            SELECT MIN(class_id) FROM classes GROUP BY subject_id, year_group, COALESCE(class_code,'')
        )
    """)
    c.execute("PRAGMA foreign_keys = ON")

    # Stage/year structure is curriculum config, not sample data — always present.
    for _sn in ('Stage 3', 'Stage 4', 'Stage 5'):
        c.execute("INSERT OR IGNORE INTO stages (stage_name) VALUES (?)", (_sn,))
    for _sn, _years in [('Stage 3', ('Year 5','Year 6')),
                        ('Stage 4', ('Year 7','Year 8')),
                        ('Stage 5', ('Year 9','Year 10'))]:
        _row = c.execute("SELECT stage_id FROM stages WHERE stage_name=?", (_sn,)).fetchone()
        if _row:
            for _yr in _years:
                c.execute("INSERT OR IGNORE INTO stage_years (stage_id, year_group) VALUES (?,?)",
                          (_row['stage_id'], _yr))

    # One-time seed: if no explicit enrollments exist yet, derive them from year_group
    # so existing data keeps working before the roster is managed manually.
    existing = c.execute("SELECT COUNT(*) FROM student_classes").fetchone()[0]
    if existing == 0:
        c.execute("""
            INSERT OR IGNORE INTO student_classes (student_id, class_id)
            SELECT s.student_id, c.class_id
            FROM students s
            JOIN classes c ON s.year_group = c.year_group
            WHERE s.year_group IS NOT NULL
        """)

    conn.commit()
    conn.close()


def seed_db():
    conn = get_db_connection()
    c = conn.cursor()

    # Skip if already seeded — checked via _meta flag so release installs stay blank.
    if c.execute("SELECT COUNT(*) FROM _meta WHERE key='seeded'").fetchone()[0]:
        conn.close()
        return

    for name in ('Mathematics', 'Science', 'English'):
        c.execute("INSERT OR IGNORE INTO subjects (subject_name) VALUES (?)", (name,))

    sci_id   = c.execute("SELECT subject_id FROM subjects WHERE subject_name = 'Science'").fetchone()['subject_id']
    stage4   = c.execute("SELECT stage_id  FROM stages  WHERE stage_name  = 'Stage 4'").fetchone()['stage_id']
    stage5   = c.execute("SELECT stage_id  FROM stages  WHERE stage_name  = 'Stage 5'").fetchone()['stage_id']

    outcomes = [
        ('SC4-WS-01', 'Observing — uses appropriate instruments and techniques to make and record observations',               1, sci_id, stage4),
        ('SC4-WS-02', 'Predicting/Questioning — formulates questions or hypotheses based on observations',                     1, sci_id, stage4),
        ('SC4-WS-03', 'Planning — designs and conducts investigations to collect valid and reliable data',                     1, sci_id, stage4),
        ('SC4-WS-04', 'Processing and Analysing — processes data and proposes evidence-based explanations',                    0, sci_id, stage4),
        ('SC4-WS-05', 'Communicating — communicates scientific understanding using appropriate representations',               0, sci_id, stage4),
        ('SC4-GEV-01','Genetics & evolutionary change — describes and explains how species change over time',                  1, sci_id, stage4),
        ('SC5-WS-01', 'Observing — selects and uses instruments independently; records data with precision',                   1, sci_id, stage5),
        ('SC5-WS-02', 'Predicting/Questioning — formulates testable questions with clearly defined variables',                 1, sci_id, stage5),
        ('SC5-WS-03', 'Planning — designs controlled investigations justifying choices of equipment and method',               1, sci_id, stage5),
        ('SC5-WS-04', 'Processing and Analysing — analyses data critically; identifies trends and anomalies',                  0, sci_id, stage5),
        ('SC5-WS-05', 'Communicating — selects and applies appropriate scientific representations for audience',               0, sci_id, stage5),
        ('SC5-GEV-01','Genetics & evolutionary change — evaluates evidence for evolution using multiple sources',              1, sci_id, stage5),
    ]
    c.executemany(
        "INSERT OR IGNORE INTO outcomes (outcome_code, outcome_name, is_theoretical, subject_id, stage_id) VALUES (?, ?, ?, ?, ?)",
        outcomes
    )

    students = [
        (10001, 'Alex',   'Smith',      'Year 7', '2024-01-15'),
        (10002, 'Blake',  'Johnson',    'Year 7', '2024-01-15'),
        (10003, 'Casey',  'Williams',   'Year 7', '2024-01-15'),
        (10004, 'Dana',   'Brown',      'Year 7', '2024-01-15'),
        (10005, 'Ellis',  'Jones',      'Year 7', '2024-01-15'),
        (10006, 'Finley', 'Garcia',     'Year 8', '2023-01-15'),
        (10007, 'Gray',   'Miller',     'Year 8', '2023-01-15'),
        (10008, 'Harper', 'Davis',      'Year 8', '2023-01-15'),
        (10009, 'Indigo', 'Rodriguez',  'Year 8', '2023-01-15'),
        (10010, 'Jordan', 'Martinez',   'Year 8', '2023-01-15'),
        (10011, 'Kai',    'Hernandez',  'Year 9', '2022-01-15'),
        (10012, 'Liam',   'Lopez',      'Year 9', '2022-01-15'),
        (10013, 'Morgan', 'Gonzalez',   'Year 9', '2022-01-15'),
        (10014, 'Noah',   'Wilson',     'Year 9', '2022-01-15'),
        (10015, 'Olivia', 'Anderson',   'Year 9', '2022-01-15'),
        (10016, 'Parker', 'Thomas',     'Year 10','2021-01-15'),
        (10017, 'Quinn',  'Taylor',     'Year 10','2021-01-15'),
        (10018, 'Riley',  'Moore',      'Year 10','2021-01-15'),
        (10019, 'Sam',    'Jackson',    'Year 10','2021-01-15'),
        (10020, 'Taylor', 'Martin',     'Year 10','2021-01-15'),
    ]
    c.executemany(
        "INSERT OR IGNORE INTO students (student_id, first_name, last_name, year_group, enrollment_date) VALUES (?, ?, ?, ?, ?)",
        students
    )

    # One class per subject at Stage 4 (Year 7) and Stage 5 (Year 9)
    math_id = c.execute("SELECT subject_id FROM subjects WHERE subject_name = 'Mathematics'").fetchone()['subject_id']
    eng_id  = c.execute("SELECT subject_id FROM subjects WHERE subject_name = 'English'").fetchone()['subject_id']
    for subj_id in (math_id, sci_id, eng_id):
        c.execute(
            "INSERT OR IGNORE INTO classes (subject_id, year_group, stage_id) VALUES (?, ?, ?)",
            (subj_id, 'Year 7', stage4)
        )
        c.execute(
            "INSERT OR IGNORE INTO classes (subject_id, year_group, stage_id) VALUES (?, ?, ?)",
            (subj_id, 'Year 9', stage5)
        )

    c.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
        ('admin', 'placeholder', 'teacher')
    )

    c.execute("INSERT OR IGNORE INTO _meta (key, value) VALUES ('seeded', 'true')")
    conn.commit()
    conn.close()


def _sparkline_svg(scores, width=90, height=28, max_val=MAX_SCORE):
    """Return an inline SVG polyline for a list of numeric scores."""
    if len(scores) < 2:
        return ''
    n = len(scores)
    pts = []
    for i, s in enumerate(scores):
        x = 2 + i * (width - 4) / (n - 1)
        y = (height - 3) - (min(s, max_val) / max_val) * (height - 6)
        pts.append(f"{x:.1f},{y:.1f}")
    points_str = ' '.join(pts)
    last = scores[-1]
    prev = scores[-2]
    colour = '#27ae60' if last >= prev else '#e74c3c' if last < prev else '#3498db'
    return (
        f'<svg width="{width}" height="{height}" '
        f'style="display:inline-block;vertical-align:middle" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<polyline points="{points_str}" fill="none" stroke="{colour}" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        f'</svg>'
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _all_classes(cursor):
    cursor.execute("""
        SELECT c.class_id,
               subj.subject_name || ' ' || c.year_group ||
                   CASE WHEN c.class_code IS NOT NULL AND c.class_code != ''
                        THEN ' (' || c.class_code || ')' ELSE '' END AS class_name,
               subj.subject_name,
               c.year_group,
               sg.stage_name,
               c.class_code
        FROM classes c
        JOIN subjects subj ON c.subject_id = subj.subject_id
        JOIN stages   sg   ON c.stage_id   = sg.stage_id
        ORDER BY c.year_group, subj.subject_name, c.class_code
    """)
    return cursor.fetchall()


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    conn = get_db_connection()
    c = conn.cursor()

    today = date.today().isoformat()
    c.execute("SELECT COUNT(*) FROM students")
    students = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM attempts")
    attempts = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM outcomes")
    outcomes_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM attempts WHERE attempt_date = ?", (today,))
    today_count = c.fetchone()[0]

    c.execute("""
        SELECT a.attempt_id, a.assessment_title, a.attempt_date,
               s.student_id, s.first_name, s.last_name,
               subj.subject_name || ' ' || c.year_group AS class_name
        FROM attempts a
        JOIN students s ON a.student_id = s.student_id
        LEFT JOIN classes c    ON a.class_id   = c.class_id
        LEFT JOIN subjects subj ON c.subject_id = subj.subject_id
        ORDER BY a.attempt_date DESC, a.attempt_id DESC
        LIMIT 8
    """)
    recent = c.fetchall()

    classes = _all_classes(c)
    conn.close()

    return render_template('index.html',
        stats=dict(students=students, attempts=attempts,
                   outcomes=outcomes_count, today=today_count),
        recent=recent,
        classes=classes,
    )


@app.route('/marks/new', methods=['GET', 'POST'])
def marks_entry():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        SELECT c.class_id AS id,
               subj.subject_name || ' ' || c.year_group ||
                   CASE WHEN c.class_code IS NOT NULL AND c.class_code != ''
                        THEN ' (' || c.class_code || ')' ELSE '' END AS class_name,
               subj.subject_name,
               c.year_group,
               c.stage_id,
               sg.stage_name
        FROM classes c
        JOIN subjects subj ON c.subject_id = subj.subject_id
        JOIN stages sg ON c.stage_id = sg.stage_id
        ORDER BY c.year_group, subj.subject_name, c.class_code
    """)
    classes = c.fetchall()

    c.execute("SELECT DISTINCT year_group FROM stage_years ORDER BY year_group")
    year_groups = [r[0] for r in c.fetchall()]

    c.execute("""
        SELECT outcome_id AS id,
               outcome_code AS code,
               outcome_name AS description,
               CASE WHEN is_theoretical THEN 'Theoretical' ELSE 'Applied' END AS focus_type,
               subject_id,
               stage_id
        FROM outcomes ORDER BY outcome_code
    """)
    outcomes = [dict(row) for row in c.fetchall()]

    if request.method == 'POST':
        try:
            student_id = int(request.form['student_id'])
            assessment_title = request.form['assessment_title'].strip()
            attempt_date = request.form['attempt_date']
            class_id = int(request.form['class_id'])

            ids_raw = request.form.get('outcome_ids', '')
            outcome_ids = [int(x) for x in ids_raw.split(',') if x.strip().isdigit()]

            if not outcome_ids:
                conn.close()
                return "No outcomes selected.", 400

            c.execute("""
                INSERT INTO attempts (student_id, class_id, attempt_date, assessment_title)
                VALUES (?, ?, ?, ?)
            """, (student_id, class_id, attempt_date, assessment_title))
            attempt_id = c.lastrowid

            for oid in outcome_ids:
                raw = request.form.get(f'score_{oid}', '0')
                score = max(0, min(MAX_SCORE, int(raw) if raw.isdigit() else 0))

                c.execute(
                    "INSERT INTO attempt_outcomes (attempt_id, outcome_id) VALUES (?, ?)",
                    (attempt_id, oid)
                )
                ao_id = c.lastrowid
                c.execute(
                    "INSERT INTO scoring_detail (attempt_outcome_id, score) VALUES (?, ?)",
                    (ao_id, score)
                )

            conn.commit()
            conn.close()
            return redirect(url_for('index'))

        except Exception as e:
            conn.rollback()
            conn.close()
            print(f"marks_entry error: {e}")
            return f"Error saving marks: {e}", 500

    conn.close()
    return render_template('marks_entry.html',
        classes=classes, outcomes=outcomes,
        year_groups=year_groups,
        today=date.today().isoformat(), max_score=MAX_SCORE,
    )


@app.route('/history')
def recent_entries():
    page = max(1, request.args.get('page', 1, type=int))
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM attempts")
    total = c.fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)

    c.execute("""
        SELECT a.attempt_id, a.assessment_title, a.attempt_date,
               s.student_id, s.first_name, s.last_name,
               subj.subject_name || ' ' || cl.year_group AS class_name,
               GROUP_CONCAT(o.outcome_code, ', ') AS outcomes
        FROM attempts a
        JOIN students s ON a.student_id = s.student_id
        LEFT JOIN classes cl   ON a.class_id   = cl.class_id
        LEFT JOIN subjects subj ON cl.subject_id = subj.subject_id
        LEFT JOIN attempt_outcomes ao ON a.attempt_id = ao.attempt_id
        LEFT JOIN outcomes o ON ao.outcome_id = o.outcome_id
        GROUP BY a.attempt_id
        ORDER BY a.attempt_date DESC, a.attempt_id DESC
        LIMIT ? OFFSET ?
    """, (per_page, offset))
    entries = c.fetchall()
    conn.close()

    return render_template('recent.html',
        entries=entries, page=page, total_pages=total_pages, total=total)


@app.route('/student/<int:student_id>')
def student_progress(student_id):
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT * FROM students WHERE student_id = ?", (student_id,))
    student = c.fetchone()
    if not student:
        conn.close()
        return "Student not found", 404

    subject_id = request.args.get('subject_id', type=int)
    stage = request.args.get('stage', '').strip()

    params = [student_id]
    extra = ""
    if subject_id:
        extra += " AND o.subject_id = ?"
        params.append(subject_id)
    if stage:
        extra += " AND sg.stage_name = ?"
        params.append(stage)

    c.execute(f"""
        SELECT o.outcome_id, o.outcome_code, o.outcome_name,
               a.attempt_date, a.assessment_title,
               sd.score, subj.subject_name, sg.stage_name
        FROM scoring_detail sd
        JOIN attempt_outcomes ao ON sd.attempt_outcome_id = ao.attempt_outcome_id
        JOIN outcomes o          ON ao.outcome_id         = o.outcome_id
        JOIN attempts a          ON ao.attempt_id         = a.attempt_id
        LEFT JOIN subjects subj  ON o.subject_id          = subj.subject_id
        LEFT JOIN stages   sg    ON o.stage_id            = sg.stage_id
        WHERE a.student_id = ?{extra}
        ORDER BY o.outcome_code, a.attempt_date
    """, params)
    rows = c.fetchall()

    outcome_data = {}
    for row in rows:
        oid = row['outcome_id']
        if oid not in outcome_data:
            outcome_data[oid] = dict(
                code=row['outcome_code'],
                name=row['outcome_name'],
                scores=[], dates=[], subjects=set(), stages=set(),
            )
        outcome_data[oid]['scores'].append(row['score'])
        outcome_data[oid]['dates'].append(row['attempt_date'])
        if row['subject_name']:
            outcome_data[oid]['subjects'].add(row['subject_name'])
        if row['stage_name']:
            outcome_data[oid]['stages'].add(row['stage_name'])

    outcome_list = []
    for oid, d in outcome_data.items():
        scores = d['scores']
        avg = round(sum(scores) / len(scores), 1)
        peak = max(scores)
        trend = ('▲' if scores[-1] > scores[-2] else '▼' if scores[-1] < scores[-2] else '—') if len(scores) > 1 else '—'
        band_label, band_css = _score_band(peak)
        flagged = (peak - avg) > DISCREPANCY_THRESHOLD
        outcome_list.append(dict(
            code=d['code'], name=d['name'],
            subjects=', '.join(sorted(d['subjects'])),
            stages=', '.join(sorted(d['stages'])),
            avg=avg, peak=peak, count=len(scores),
            trend=trend,
            band_label=band_label, band_css=band_css,
            flagged=flagged,
            sparkline=_sparkline_svg(scores),
        ))
    outcome_list.sort(key=lambda x: x['code'])

    # ── Coverage gaps ────────────────────────────────────────────────────────
    # Outcomes for this student's stage (derived from year_group) that have
    # never been assessed for them.  Subject filter applies; stage is implicit.
    gaps_params = [student_id, student_id]
    gaps_extra  = ""
    if subject_id:
        gaps_extra = " AND o.subject_id = ?"
        gaps_params.append(subject_id)

    c.execute(f"""
        SELECT o.outcome_id, o.outcome_code, o.outcome_name, o.is_theoretical,
               COALESCE(subj.subject_name, 'Unassigned') AS subject_name,
               COALESCE(sg.stage_name, '')               AS stage_name
        FROM outcomes o
        LEFT JOIN subjects subj ON o.subject_id = subj.subject_id
        LEFT JOIN stages   sg   ON o.stage_id   = sg.stage_id
        JOIN stage_years   sy   ON o.stage_id   = sy.stage_id
        WHERE sy.year_group = (SELECT year_group FROM students WHERE student_id = ?)
          AND o.outcome_id NOT IN (
              SELECT DISTINCT ao.outcome_id
              FROM attempt_outcomes ao
              JOIN attempts a ON ao.attempt_id = a.attempt_id
              WHERE a.student_id = ?
          )
        {gaps_extra}
        ORDER BY subj.subject_name, o.outcome_code
    """, gaps_params)
    gaps = c.fetchall()

    # ── Raw history (for audit trail / on-screen + export) ────────────────
    hist_params = [student_id]
    hist_extra  = ""
    if subject_id:
        hist_extra = " AND o.subject_id = ?"
        hist_params.append(subject_id)
    # stage filter intentionally omitted from history — show full record

    c.execute(f"""
        SELECT a.attempt_date, a.assessment_title,
               COALESCE(subj.subject_name, '') AS subject_name,
               CASE
                   WHEN cl.class_id IS NOT NULL THEN
                       subj.subject_name || ' ' || cl.year_group ||
                       CASE WHEN cl.class_code IS NOT NULL AND cl.class_code != ''
                            THEN ' (' || cl.class_code || ')' ELSE '' END
                   ELSE 'Cross-curricular'
               END AS class_name,
               o.outcome_code, o.outcome_name,
               CASE WHEN o.is_theoretical THEN 'Theoretical' ELSE 'Applied' END AS focus_type,
               sd.score
        FROM scoring_detail sd
        JOIN attempt_outcomes ao ON sd.attempt_outcome_id = ao.attempt_outcome_id
        JOIN outcomes o          ON ao.outcome_id         = o.outcome_id
        JOIN attempts a          ON ao.attempt_id         = a.attempt_id
        LEFT JOIN classes  cl    ON a.class_id            = cl.class_id
        LEFT JOIN subjects subj  ON cl.subject_id         = subj.subject_id
        WHERE a.student_id = ?{hist_extra}
        ORDER BY a.attempt_date DESC, a.attempt_id DESC, o.outcome_code
    """, hist_params)
    history_rows = c.fetchall()

    c.execute("SELECT subject_id, subject_name FROM subjects ORDER BY subject_name")
    subjects = c.fetchall()
    c.execute("SELECT stage_name FROM stages ORDER BY stage_id")
    stages = [r[0] for r in c.fetchall()]

    conn.close()
    return render_template('student_progress.html',
        student=student,
        outcome_list=outcome_list,
        gaps=gaps,
        history_rows=history_rows,
        subjects=subjects, stages=stages,
        current_subject_id=subject_id,
        current_stage=stage,
        max_score=MAX_SCORE,
        bands=BANDS,
        discrepancy_threshold=DISCREPANCY_THRESHOLD,
    )


@app.route('/analytics')
def analytics():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        SELECT c.class_id,
               subj.subject_name || ' ' || c.year_group AS class_name,
               subj.subject_name,
               c.year_group,
               sg.stage_name,
               COUNT(DISTINCT a.student_id) AS student_count,
               COUNT(a.attempt_id) AS attempt_count
        FROM classes c
        JOIN subjects subj ON c.subject_id = subj.subject_id
        JOIN stages sg ON c.stage_id = sg.stage_id
        LEFT JOIN attempts a ON c.class_id = a.class_id
        GROUP BY c.class_id
        ORDER BY c.year_group, subj.subject_name
    """)
    classes = c.fetchall()

    c.execute("""
        SELECT s.student_id,
               s.first_name || ' ' || s.last_name AS name,
               s.year_group,
               COALESCE(sg.stage_name, '') AS stage_name,
               COUNT(DISTINCT a.attempt_id) AS attempt_count
        FROM students s
        LEFT JOIN stage_years sy ON s.year_group = sy.year_group
        LEFT JOIN stages sg ON sy.stage_id = sg.stage_id
        LEFT JOIN attempts a ON s.student_id = a.student_id
        GROUP BY s.student_id
        ORDER BY s.last_name, s.first_name
    """)
    students = c.fetchall()

    c.execute("SELECT stage_name FROM stages ORDER BY stage_id")
    stages = [r[0] for r in c.fetchall()]

    c.execute("SELECT DISTINCT year_group FROM stage_years ORDER BY year_group")
    year_groups = [r[0] for r in c.fetchall()]

    c.execute("SELECT subject_id, subject_name FROM subjects ORDER BY subject_name")
    subjects = c.fetchall()

    c.execute("""
        SELECT sg.stage_name, sy.year_group
        FROM stage_years sy
        JOIN stages sg ON sy.stage_id = sg.stage_id
        ORDER BY sg.stage_id, sy.year_group
    """)
    stage_year_map = {}
    for row in c.fetchall():
        stage_year_map.setdefault(row[0], []).append(row[1])

    conn.close()

    return render_template('analytics.html', classes=classes, students=students,
                           stages=stages, year_groups=year_groups, subjects=subjects,
                           stage_year_map=stage_year_map)


@app.route('/marks/bulk', methods=['GET', 'POST'])
def bulk_entry():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        SELECT c.class_id AS id,
               subj.subject_name || ' ' || c.year_group ||
                   CASE WHEN c.class_code IS NOT NULL AND c.class_code != ''
                        THEN ' (' || c.class_code || ')' ELSE '' END AS class_name,
               subj.subject_name, c.year_group, c.stage_id, sg.stage_name
        FROM classes c
        JOIN subjects subj ON c.subject_id = subj.subject_id
        JOIN stages sg ON c.stage_id = sg.stage_id
        ORDER BY c.year_group, subj.subject_name, c.class_code
    """)
    classes = c.fetchall()

    c.execute("SELECT DISTINCT year_group FROM stage_years ORDER BY year_group")
    year_groups = [r[0] for r in c.fetchall()]

    c.execute("""
        SELECT outcome_id AS id, outcome_code AS code, outcome_name AS description,
               CASE WHEN is_theoretical THEN 'Theoretical' ELSE 'Applied' END AS focus_type,
               subject_id, stage_id
        FROM outcomes ORDER BY outcome_code
    """)
    outcomes = [dict(row) for row in c.fetchall()]

    if request.method == 'POST':
        assessment_title = request.form.get('assessment_title', '').strip()
        attempt_date     = request.form.get('attempt_date', date.today().isoformat())
        class_id_raw     = request.form.get('class_id', '').strip()
        class_id         = int(class_id_raw) if class_id_raw.isdigit() else None
        outcome_ids      = [int(x) for x in request.form.get('outcome_ids', '').split(',') if x.strip().isdigit()]
        student_ids      = [int(x) for x in request.form.get('student_ids', '').split(',') if x.strip().isdigit()]

        if not assessment_title or not outcome_ids or not student_ids:
            conn.close()
            return render_template('bulk_entry.html',
                classes=classes, year_groups=year_groups, outcomes=outcomes,
                error='Assessment title, at least one outcome, and at least one student are required.',
                today=date.today().isoformat(), max_score=MAX_SCORE)

        results, saved, skipped = [], 0, 0

        for student_id in student_ids:
            stu = c.execute(
                "SELECT first_name, last_name FROM students WHERE student_id=?", (student_id,)
            ).fetchone()
            if not stu:
                skipped += 1
                results.append({'name': f'ID {student_id}', 'status': 'skipped', 'detail': 'Student not found'})
                continue

            full_name = f"{stu['last_name']}, {stu['first_name']}"
            scores = []
            for oid in outcome_ids:
                raw = request.form.get(f's{student_id}o{oid}', '').strip()
                if raw and raw.isdigit():
                    scores.append((oid, max(0, min(MAX_SCORE, int(raw)))))

            if not scores:
                skipped += 1
                results.append({'name': full_name, 'status': 'skipped', 'detail': 'No scores entered'})
                continue

            c.execute(
                "INSERT INTO attempts (student_id, class_id, attempt_date, assessment_title) VALUES (?,?,?,?)",
                (student_id, class_id, attempt_date, assessment_title)
            )
            attempt_id = c.lastrowid
            for oid, score in scores:
                c.execute("INSERT INTO attempt_outcomes (attempt_id, outcome_id) VALUES (?,?)", (attempt_id, oid))
                c.execute("INSERT INTO scoring_detail (attempt_outcome_id, score) VALUES (?,?)", (c.lastrowid, score))

            saved += 1
            results.append({'name': full_name, 'status': 'ok',
                             'detail': f'{len(scores)} outcome{"s" if len(scores)!=1 else ""} saved'})

        conn.commit()
        conn.close()
        return render_template('bulk_entry.html',
            classes=classes, year_groups=year_groups, outcomes=outcomes,
            results=results, saved=saved, skipped=skipped,
            today=date.today().isoformat(), max_score=MAX_SCORE)

    conn.close()
    return render_template('bulk_entry.html',
        classes=classes, year_groups=year_groups, outcomes=outcomes,
        today=date.today().isoformat(), max_score=MAX_SCORE)


@app.route('/analytics/class/<int:class_id>')
def class_analytics(class_id):
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        SELECT c.class_id, c.subject_id, c.stage_id,
               subj.subject_name || ' ' || c.year_group ||
                   CASE WHEN c.class_code IS NOT NULL AND c.class_code != ''
                        THEN ' (' || c.class_code || ')' ELSE '' END AS class_name
        FROM classes c
        JOIN subjects subj ON c.subject_id = subj.subject_id
        WHERE c.class_id = ?
    """, (class_id,))
    class_info = c.fetchone()
    if not class_info:
        conn.close()
        return "Class not found", 404

    subject_id = class_info['subject_id']
    stage_id   = class_info['stage_id']

    view_mode = request.args.get('view', 'peak')
    agg = 'MAX' if view_mode == 'peak' else 'AVG'

    # Include attempts directly assigned to this class, plus unclassified attempts
    # where the outcome belongs to this class's subject+stage and the student is enrolled here.
    c.execute(f"""
        SELECT s.student_id,
               s.first_name || ' ' || s.last_name AS student_name,
               o.outcome_id, o.outcome_code, o.outcome_name,
               {agg}(sd.score) AS avg_score,
               COUNT(sd.score) AS attempt_count
        FROM scoring_detail sd
        JOIN attempt_outcomes ao ON sd.attempt_outcome_id = ao.attempt_outcome_id
        JOIN outcomes o          ON ao.outcome_id         = o.outcome_id
        JOIN attempts a          ON ao.attempt_id         = a.attempt_id
        JOIN students s          ON a.student_id          = s.student_id
        WHERE (
            a.class_id = ?
            OR (
                a.class_id IS NULL
                AND o.subject_id = ?
                AND o.stage_id   = ?
                AND EXISTS (
                    SELECT 1 FROM student_classes sc
                    WHERE sc.student_id = a.student_id AND sc.class_id = ?
                )
            )
        )
        GROUP BY s.student_id, o.outcome_id
        ORDER BY o.outcome_code, s.last_name, s.first_name
    """, (class_id, subject_id, stage_id, class_id))
    rows = c.fetchall()

    students_map = {}   # student_id -> name
    outcomes_map = {}   # outcome_id -> (code, name)
    grid = {}           # (student_id, outcome_id) -> avg_score

    for row in rows:
        students_map[row['student_id']] = row['student_name']
        outcomes_map[row['outcome_id']] = (row['outcome_code'], row['outcome_name'])
        avg = round(row['avg_score'], 1)
        _, band_css = _score_band(round(avg))
        grid[(row['student_id'], row['outcome_id'])] = (avg, row['attempt_count'], band_css)

    students_list = sorted(students_map.items(), key=lambda x: x[1])
    outcomes_list = sorted(outcomes_map.items(), key=lambda x: x[1][0])

    # Class averages per outcome
    _oid_scores = {}
    for (sid, oid), (avg, cnt, _css) in grid.items():
        _oid_scores.setdefault(oid, []).append(avg)
    outcome_avgs = {}
    for oid, vals in _oid_scores.items():
        avg = round(sum(vals) / len(vals), 1)
        _, band_css = _score_band(round(avg))
        outcome_avgs[oid] = (avg, band_css)

    all_classes = _all_classes(c)
    conn.close()

    return render_template('class_analytics.html',
        class_info=class_info,
        students=students_list,
        outcomes=outcomes_list,
        grid=grid,
        outcome_avgs=outcome_avgs,
        all_classes=all_classes,
        max_score=MAX_SCORE,
        view_mode=view_mode,
    )


@app.route('/marks/import', methods=['GET', 'POST'])
def import_marks():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        SELECT c.class_id AS id,
               subj.subject_name || ' ' || c.year_group ||
                   CASE WHEN c.class_code IS NOT NULL AND c.class_code != ''
                        THEN ' (' || c.class_code || ')' ELSE '' END AS class_name,
               subj.subject_name, c.year_group, sg.stage_name
        FROM classes c
        JOIN subjects subj ON c.subject_id = subj.subject_id
        JOIN stages sg ON c.stage_id = sg.stage_id
        ORDER BY c.year_group, subj.subject_name, c.class_code
    """)
    classes = c.fetchall()

    c.execute("SELECT DISTINCT year_group FROM stage_years ORDER BY year_group")
    year_groups = [r[0] for r in c.fetchall()]

    if request.method == 'POST':
        assessment_title = request.form.get('assessment_title', '').strip()
        attempt_date     = request.form.get('attempt_date', date.today().isoformat())
        class_id_raw     = request.form.get('class_id', '').strip()
        class_id         = int(class_id_raw) if class_id_raw.isdigit() else None
        uploaded         = request.files.get('csv_file')

        if not uploaded or not assessment_title:
            conn.close()
            return render_template('import_marks.html',
                classes=classes, year_groups=year_groups,
                error='Assessment title and CSV file are both required.',
                today=date.today().isoformat())

        SKIP_COLS = {'Name', 'Student ID', 'Scale Average', 'Comment'}

        text    = uploaded.stream.read().decode('utf-8-sig')
        reader  = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        outcome_cols = [h for h in headers if h not in SKIP_COLS]

        # outcome code is the first whitespace-separated token of the column header
        def parse_code(col):
            parts = col.split()
            return parts[0] if parts else col

        c.execute("SELECT outcome_id, outcome_code FROM outcomes")
        outcome_map = {row['outcome_code']: row['outcome_id'] for row in c.fetchall()}

        results  = []
        imported = 0
        skipped  = 0

        for row in reader:
            student_name   = (row.get('Name') or '').strip()
            student_id_raw = (row.get('Student ID') or '').strip()

            if not student_id_raw:
                skipped += 1
                results.append({'name': student_name or '(blank)', 'status': 'skipped', 'detail': 'No Student ID'})
                continue

            try:
                student_id = int(student_id_raw)
            except ValueError:
                skipped += 1
                results.append({'name': student_name, 'status': 'skipped', 'detail': f'Invalid Student ID: {student_id_raw}'})
                continue

            student = c.execute(
                "SELECT student_id, first_name, last_name FROM students WHERE student_id = ?",
                (student_id,)
            ).fetchone()
            if not student:
                skipped += 1
                results.append({'name': student_name, 'status': 'skipped',
                                 'detail': f'Student ID {student_id} not found in database'})
                continue

            full_name = f"{student['first_name']} {student['last_name']}"
            scores   = []
            warnings = []

            for col in outcome_cols:
                val = (row.get(col) or '').strip()
                if not val:
                    continue
                try:
                    score = int(round(float(val)))
                except ValueError:
                    continue
                code = parse_code(col)
                oid  = outcome_map.get(code)
                if oid is None:
                    warnings.append(f'outcome {code} not found')
                    continue
                scores.append((oid, max(0, min(MAX_SCORE, score))))

            if not scores:
                skipped += 1
                results.append({'name': full_name, 'status': 'skipped', 'detail': 'No scoreable outcomes in this row'})
                continue

            c.execute(
                "INSERT INTO attempts (student_id, class_id, attempt_date, assessment_title) VALUES (?, ?, ?, ?)",
                (student_id, class_id, attempt_date, assessment_title)
            )
            attempt_id = c.lastrowid

            for oid, score in scores:
                c.execute("INSERT INTO attempt_outcomes (attempt_id, outcome_id) VALUES (?, ?)", (attempt_id, oid))
                c.execute("INSERT INTO scoring_detail (attempt_outcome_id, score) VALUES (?, ?)", (c.lastrowid, score))

            imported += 1
            detail = f'{len(scores)} outcome{"s" if len(scores) != 1 else ""} imported'
            if warnings:
                detail += f' — warnings: {", ".join(warnings)}'
            results.append({'name': full_name, 'status': 'ok', 'detail': detail})

        conn.commit()
        conn.close()
        return render_template('import_marks.html',
            classes=classes, year_groups=year_groups,
            results=results, imported=imported, skipped=skipped,
            today=date.today().isoformat())

    conn.close()
    return render_template('import_marks.html',
        classes=classes, year_groups=year_groups,
        today=date.today().isoformat())


@app.route('/settings')
def settings():
    conn = get_db_connection()
    c = conn.cursor()
    student_count = c.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    class_count   = c.execute("SELECT COUNT(*) FROM classes").fetchone()[0]
    subject_count = c.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
    conn.close()
    return render_template('settings.html',
        student_count=student_count, class_count=class_count, subject_count=subject_count)


@app.route('/settings/students')
def manage_students():
    q   = request.args.get('q', '').strip()
    yr  = request.args.get('year', '').strip()
    where, params = [], []
    if q:
        like = f'%{q}%'
        where.append("(s.first_name LIKE ? OR s.last_name LIKE ? OR CAST(s.student_id AS TEXT) LIKE ?)")
        params += [like, like, like]
    if yr:
        where.append("s.year_group = ?")
        params.append(yr)

    conn = get_db_connection()
    c = conn.cursor()
    sql = """
        SELECT s.student_id, s.first_name, s.last_name, s.year_group, s.enrollment_date,
               COUNT(DISTINCT a.attempt_id) AS attempt_count
        FROM students s
        LEFT JOIN attempts a ON s.student_id = a.student_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY s.student_id ORDER BY s.last_name, s.first_name"
    c.execute(sql, params)
    students = c.fetchall()

    c.execute("SELECT DISTINCT year_group FROM stage_years ORDER BY year_group")
    year_groups = [r[0] for r in c.fetchall()]
    conn.close()
    return render_template('students_manage.html',
        students=students, year_groups=year_groups, q=q, current_year=yr)


@app.route('/settings/students/new', methods=['GET', 'POST'])
def new_student():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT year_group FROM stage_years ORDER BY year_group")
    year_groups = [r[0] for r in c.fetchall()]
    error = None

    if request.method == 'POST':
        try:
            student_id = int(request.form['student_id'])
            first_name = request.form['first_name'].strip()
            last_name  = request.form['last_name'].strip()
            year_group = request.form.get('year_group', '').strip() or None
            enrol_date = request.form.get('enrollment_date') or date.today().isoformat()
            if not first_name or not last_name:
                raise ValueError("First and last name are required.")
            c.execute(
                "INSERT INTO students (student_id, first_name, last_name, year_group, enrollment_date) VALUES (?,?,?,?,?)",
                (student_id, first_name, last_name, year_group, enrol_date)
            )
            conn.commit()
            conn.close()
            return redirect(url_for('manage_students'))
        except sqlite3.IntegrityError:
            error = f"Student ID {request.form.get('student_id')} already exists."
        except (ValueError, TypeError) as e:
            error = str(e)

    conn.close()
    return render_template('student_form.html',
        year_groups=year_groups, mode='new', error=error,
        student=None, today=date.today().isoformat())


@app.route('/settings/student/<int:student_id>/edit', methods=['GET', 'POST'])
def edit_student(student_id):
    conn = get_db_connection()
    c = conn.cursor()
    student = c.execute("SELECT * FROM students WHERE student_id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        return "Student not found", 404

    c.execute("SELECT DISTINCT year_group FROM stage_years ORDER BY year_group")
    year_groups = [r[0] for r in c.fetchall()]
    error = None

    if request.method == 'POST':
        first_name = request.form['first_name'].strip()
        last_name  = request.form['last_name'].strip()
        year_group = request.form.get('year_group', '').strip() or None
        if not first_name or not last_name:
            error = "First and last name are required."
        else:
            c.execute(
                "UPDATE students SET first_name=?, last_name=?, year_group=? WHERE student_id=?",
                (first_name, last_name, year_group, student_id)
            )
            conn.commit()
            conn.close()
            return redirect(url_for('manage_students'))

    conn.close()
    return render_template('student_form.html',
        year_groups=year_groups, mode='edit', error=error, student=student,
        today=date.today().isoformat())


@app.route('/settings/students/import', methods=['GET', 'POST'])
def import_students():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT year_group FROM stage_years ORDER BY year_group")
    year_groups = [r[0] for r in c.fetchall()]

    if request.method == 'POST':
        uploaded = request.files.get('csv_file')
        if not uploaded:
            conn.close()
            return render_template('student_import.html', year_groups=year_groups,
                error='Please select a CSV file.')

        text   = uploaded.stream.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text))
        results, imported, updated, skipped = [], 0, 0, 0

        for row in reader:
            id_raw     = (row.get('student_id') or row.get('Student ID') or '').strip()
            first_name = (row.get('first_name') or row.get('First Name') or '').strip()
            last_name  = (row.get('last_name')  or row.get('Last Name')  or row.get('Surname') or '').strip()
            year_group = (row.get('year_group') or row.get('Year Group') or row.get('Year') or '').strip() or None

            if not id_raw or not first_name or not last_name:
                skipped += 1
                results.append({'name': f"{first_name} {last_name}".strip() or '(blank)',
                                 'status': 'skipped', 'detail': 'Missing required field(s)'})
                continue
            try:
                student_id = int(id_raw)
            except ValueError:
                skipped += 1
                results.append({'name': f"{first_name} {last_name}", 'status': 'skipped',
                                 'detail': f'Invalid Student ID: {id_raw}'})
                continue

            existing = c.execute("SELECT 1 FROM students WHERE student_id=?", (student_id,)).fetchone()
            c.execute("""
                INSERT INTO students (student_id, first_name, last_name, year_group, enrollment_date)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(student_id) DO UPDATE SET
                    first_name = excluded.first_name,
                    last_name  = excluded.last_name,
                    year_group = excluded.year_group
            """, (student_id, first_name, last_name, year_group, date.today().isoformat()))

            if existing:
                updated += 1
                results.append({'name': f"{first_name} {last_name}", 'status': 'updated',
                                 'detail': f'ID {student_id} — record updated'})
            else:
                imported += 1
                results.append({'name': f"{first_name} {last_name}", 'status': 'ok',
                                 'detail': f'ID {student_id} — new student added'})

        conn.commit()
        conn.close()
        return render_template('student_import.html', year_groups=year_groups,
            results=results, imported=imported, updated=updated, skipped=skipped)

    conn.close()
    return render_template('student_import.html', year_groups=year_groups)


@app.route('/settings/classes', methods=['GET', 'POST'])
def manage_classes():
    conn = get_db_connection()
    c = conn.cursor()
    error = None

    if request.method == 'POST':
        action     = request.form.get('action', 'add')
        subject_id = request.form.get('subject_id', '').strip()
        year_group = request.form.get('year_group', '').strip()
        class_code = request.form.get('class_code', '').strip() or None

        if action == 'add':
            if not subject_id or not year_group:
                error = "Subject and year group are required."
            else:
                stage = c.execute("""
                    SELECT sg.stage_id FROM stage_years sy
                    JOIN stages sg ON sy.stage_id = sg.stage_id
                    WHERE sy.year_group = ?
                """, (year_group,)).fetchone()
                if not stage:
                    error = f"No stage is configured for {year_group}."
                else:
                    try:
                        c.execute(
                            "INSERT INTO classes (subject_id, year_group, stage_id, class_code) VALUES (?,?,?,?)",
                            (int(subject_id), year_group, stage['stage_id'], class_code)
                        )
                        conn.commit()
                    except sqlite3.Error as e:
                        error = str(e)

        elif action == 'update_code':
            class_id   = request.form.get('class_id', '').strip()
            if class_id:
                c.execute("UPDATE classes SET class_code=? WHERE class_id=?",
                          (class_code, int(class_id)))
                conn.commit()

    classes = _all_classes(c)
    c.execute("SELECT subject_id, subject_name FROM subjects ORDER BY subject_name")
    subjects = c.fetchall()
    c.execute("SELECT DISTINCT year_group FROM stage_years ORDER BY year_group")
    year_groups = [r[0] for r in c.fetchall()]
    conn.close()
    return render_template('classes_manage.html',
        classes=classes, subjects=subjects, year_groups=year_groups, error=error)


@app.route('/settings/subjects', methods=['GET', 'POST'])
def manage_subjects():
    conn = get_db_connection()
    c = conn.cursor()
    error = None

    if request.method == 'POST':
        name = request.form.get('subject_name', '').strip()
        if not name:
            error = "Subject name is required."
        else:
            try:
                c.execute("INSERT INTO subjects (subject_name) VALUES (?)", (name,))
                conn.commit()
            except sqlite3.IntegrityError:
                error = f'"{name}" already exists.'

    c.execute("SELECT subject_id, subject_name FROM subjects ORDER BY subject_name")
    subjects = c.fetchall()
    conn.close()
    return render_template('subjects_manage.html', subjects=subjects, error=error)


@app.route('/api/students_by_class')
def api_students_by_class():
    class_id = request.args.get('class_id', type=int)
    if not class_id:
        return jsonify([])
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT s.student_id AS id, s.first_name, s.last_name, s.year_group
        FROM students s
        JOIN student_classes sc ON s.student_id = sc.student_id
        WHERE sc.class_id = ?
        ORDER BY s.last_name, s.first_name
    """, (class_id,))
    students = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(students)


@app.route('/settings/class/<int:class_id>/roster', methods=['GET', 'POST'])
def class_roster(class_id):
    conn = get_db_connection()
    c = conn.cursor()

    cls = c.execute("""
        SELECT c.class_id,
               subj.subject_name || ' ' || c.year_group ||
                   CASE WHEN c.class_code IS NOT NULL AND c.class_code != ''
                        THEN ' (' || c.class_code || ')' ELSE '' END AS class_name,
               c.year_group, sg.stage_name
        FROM classes c
        JOIN subjects subj ON c.subject_id = subj.subject_id
        JOIN stages sg ON c.stage_id = sg.stage_id
        WHERE c.class_id = ?
    """, (class_id,)).fetchone()
    if not cls:
        conn.close()
        return "Class not found", 404

    if request.method == 'POST':
        action     = request.form.get('action')
        student_id = request.form.get('student_id', type=int)
        if action == 'add' and student_id:
            c.execute("INSERT OR IGNORE INTO student_classes (student_id, class_id) VALUES (?, ?)",
                      (student_id, class_id))
            conn.commit()
        elif action == 'remove' and student_id:
            c.execute("DELETE FROM student_classes WHERE student_id=? AND class_id=?",
                      (student_id, class_id))
            conn.commit()

    # Enrolled students
    c.execute("""
        SELECT s.student_id, s.first_name, s.last_name, s.year_group
        FROM students s
        JOIN student_classes sc ON s.student_id = sc.student_id
        WHERE sc.class_id = ?
        ORDER BY s.last_name, s.first_name
    """, (class_id,))
    enrolled = c.fetchall()
    enrolled_ids = {r['student_id'] for r in enrolled}

    # Search for students to add
    q = request.args.get('q', '').strip()
    search_results = []
    if q:
        like = f'%{q}%'
        c.execute("""
            SELECT student_id, first_name, last_name, year_group
            FROM students
            WHERE (first_name LIKE ? OR last_name LIKE ? OR CAST(student_id AS TEXT) LIKE ?)
            ORDER BY last_name, first_name
            LIMIT 30
        """, (like, like, like))
        search_results = [r for r in c.fetchall() if r['student_id'] not in enrolled_ids]

    conn.close()
    return render_template('class_roster.html',
        cls=cls, enrolled=enrolled, search_results=search_results, q=q)


@app.route('/settings/outcomes', methods=['GET', 'POST'])
def manage_outcomes():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT subject_id, subject_name FROM subjects ORDER BY subject_name")
    subjects = c.fetchall()
    c.execute("SELECT stage_id, stage_name FROM stages ORDER BY stage_id")
    stages = c.fetchall()

    error = None

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update':
            oid        = request.form.get('outcome_id', type=int)
            subject_id = request.form.get('subject_id', '').strip() or None
            stage_id   = request.form.get('stage_id',   '').strip() or None
            if oid:
                c.execute(
                    "UPDATE outcomes SET subject_id=?, stage_id=? WHERE outcome_id=?",
                    (subject_id, stage_id, oid)
                )
                conn.commit()

        elif action == 'add':
            code       = request.form.get('outcome_code', '').strip().upper()
            name       = request.form.get('outcome_name', '').strip()
            focus      = request.form.get('is_theoretical', '1')
            subject_id = request.form.get('subject_id', '').strip() or None
            stage_id   = request.form.get('stage_id',   '').strip() or None
            if not code or not name:
                error = "Outcome code and description are required."
            else:
                try:
                    c.execute("""
                        INSERT INTO outcomes (outcome_code, outcome_name, is_theoretical, subject_id, stage_id)
                        VALUES (?, ?, ?, ?, ?)
                    """, (code, name, int(focus), subject_id, stage_id))
                    conn.commit()
                except sqlite3.IntegrityError:
                    error = f'Outcome code "{code}" already exists.'

    # Build filter
    f_subject = request.args.get('subject', '').strip()
    f_stage   = request.args.get('stage',   '').strip()
    f_unset   = request.args.get('unset', '')

    where, params = [], []
    if f_subject:
        where.append("o.subject_id = ?"); params.append(int(f_subject))
    if f_stage:
        where.append("o.stage_id = ?"); params.append(int(f_stage))
    if f_unset:
        where.append("(o.subject_id IS NULL OR o.stage_id IS NULL)")

    sql = """
        SELECT o.outcome_id, o.outcome_code, o.outcome_name, o.is_theoretical,
               o.subject_id, o.stage_id,
               subj.subject_name, sg.stage_name
        FROM outcomes o
        LEFT JOIN subjects subj ON o.subject_id = subj.subject_id
        LEFT JOIN stages   sg   ON o.stage_id   = sg.stage_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY o.outcome_code"
    c.execute(sql, params)
    outcomes = c.fetchall()

    unset_count = c.execute(
        "SELECT COUNT(*) FROM outcomes WHERE subject_id IS NULL OR stage_id IS NULL"
    ).fetchone()[0]

    conn.close()
    return render_template('outcomes_manage.html',
        outcomes=outcomes, subjects=subjects, stages=stages,
        f_subject=f_subject, f_stage=f_stage, f_unset=f_unset,
        unset_count=unset_count, error=error)


@app.route('/api/outcomes')
def api_outcomes():
    q = request.args.get('q', '').strip()
    conn = get_db_connection()
    c = conn.cursor()
    if q:
        like = f'%{q}%'
        c.execute("""
            SELECT outcome_id AS id, outcome_code AS code,
                   outcome_name AS description,
                   CASE WHEN is_theoretical THEN 'Theoretical' ELSE 'Applied' END AS focus_type
            FROM outcomes
            WHERE outcome_code LIKE ? OR outcome_name LIKE ?
            LIMIT 20
        """, (like, like))
    else:
        c.execute("""
            SELECT outcome_id AS id, outcome_code AS code,
                   outcome_name AS description,
                   CASE WHEN is_theoretical THEN 'Theoretical' ELSE 'Applied' END AS focus_type
            FROM outcomes LIMIT 20
        """)
    results = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(results)


@app.route('/student/<int:student_id>/export')
def student_export(student_id):
    """Download the student's full assessment history as a CSV file."""
    subject_id = request.args.get('subject_id', type=int)

    conn = get_db_connection()
    c = conn.cursor()
    student = c.execute("SELECT * FROM students WHERE student_id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        return "Student not found", 404

    params = [student_id]
    extra  = ""
    if subject_id:
        extra = " AND o.subject_id = ?"
        params.append(subject_id)

    c.execute(f"""
        SELECT a.attempt_date, a.assessment_title,
               COALESCE(subj.subject_name, '') AS subject_name,
               CASE
                   WHEN cl.class_id IS NOT NULL THEN
                       subj.subject_name || ' ' || cl.year_group ||
                       CASE WHEN cl.class_code IS NOT NULL AND cl.class_code != ''
                            THEN ' (' || cl.class_code || ')' ELSE '' END
                   ELSE 'Cross-curricular'
               END AS class_name,
               o.outcome_code, o.outcome_name,
               CASE WHEN o.is_theoretical THEN 'Theoretical' ELSE 'Applied' END AS focus_type,
               sd.score
        FROM scoring_detail sd
        JOIN attempt_outcomes ao ON sd.attempt_outcome_id = ao.attempt_outcome_id
        JOIN outcomes o          ON ao.outcome_id         = o.outcome_id
        JOIN attempts a          ON ao.attempt_id         = a.attempt_id
        LEFT JOIN classes  cl    ON a.class_id            = cl.class_id
        LEFT JOIN subjects subj  ON cl.subject_id         = subj.subject_id
        WHERE a.student_id = ?{extra}
        ORDER BY a.attempt_date, a.attempt_id, o.outcome_code
    """, params)
    rows = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Date', 'Assessment Title', 'Subject', 'Class',
        'Outcome Code', 'Outcome Description', 'Type',
        f'Score (/{MAX_SCORE})',
    ])
    for row in rows:
        writer.writerow([
            row['attempt_date'], row['assessment_title'],
            row['subject_name'], row['class_name'],
            row['outcome_code'], row['outcome_name'],
            row['focus_type'], row['score'],
        ])

    name_slug = f"{student['last_name']}_{student['first_name']}"
    filename  = f"UDL_{name_slug}_assessment_history.csv"
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


if __name__ == '__main__':
    init_db()
    seed_db()
    app.run(debug=True)
