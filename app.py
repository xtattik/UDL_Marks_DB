import sqlite3
from collections import defaultdict
from datetime import date
from flask import Flask, render_template, request, redirect, url_for, jsonify

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
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL
        )
    """)

    # Migrate existing databases that predate these schema changes
    _migrations = [
        "ALTER TABLE students ADD COLUMN year_group TEXT",
        "ALTER TABLE classes  RENAME COLUMN grade_level TO year_group",
        "ALTER TABLE classes  ADD COLUMN stage_id INTEGER REFERENCES stages(stage_id)",
        "ALTER TABLE outcomes ADD COLUMN subject_id INTEGER REFERENCES subjects(subject_id)",
        "ALTER TABLE outcomes ADD COLUMN stage_id   INTEGER REFERENCES stages(stage_id)",
        "ALTER TABLE attempts DROP COLUMN class_id",  # will fail gracefully — replaced by nullable below
    ]
    for sql in _migrations:
        try:
            c.execute(sql)
        except Exception:
            pass

    conn.commit()
    conn.close()


def seed_db():
    conn = get_db_connection()
    c = conn.cursor()

    for name in ('Mathematics', 'Science', 'English'):
        c.execute("INSERT OR IGNORE INTO subjects (subject_name) VALUES (?)", (name,))

    for stage_name in ('Stage 3', 'Stage 4', 'Stage 5'):
        c.execute("INSERT OR IGNORE INTO stages (stage_name) VALUES (?)", (stage_name,))

    stage_year_map = {
        'Stage 3': ('Year 5', 'Year 6'),
        'Stage 4': ('Year 7', 'Year 8'),
        'Stage 5': ('Year 9', 'Year 10'),
    }
    for stage_name, years in stage_year_map.items():
        row = c.execute("SELECT stage_id FROM stages WHERE stage_name = ?", (stage_name,)).fetchone()
        if row:
            for yr in years:
                c.execute(
                    "INSERT OR IGNORE INTO stage_years (stage_id, year_group) VALUES (?, ?)",
                    (row['stage_id'], yr)
                )

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
               subj.subject_name || ' ' || c.year_group AS class_name,
               subj.subject_name,
               c.year_group,
               sg.stage_name
        FROM classes c
        JOIN subjects subj ON c.subject_id = subj.subject_id
        JOIN stages   sg   ON c.stage_id   = sg.stage_id
        ORDER BY subj.subject_name, c.year_group
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
        SELECT student_id AS id, first_name, last_name
        FROM students ORDER BY last_name, first_name
    """)
    students = c.fetchall()

    c.execute("""
        SELECT c.class_id AS id,
               subj.subject_name || ' ' || c.year_group AS class_name,
               subj.subject_name
        FROM classes c
        JOIN subjects subj ON c.subject_id = subj.subject_id
        ORDER BY subj.subject_name, c.year_group
    """)
    classes = c.fetchall()

    c.execute("""
        SELECT outcome_id AS id,
               outcome_code AS code,
               outcome_name AS description,
               CASE WHEN is_theoretical THEN 'Theoretical' ELSE 'Applied' END AS focus_type,
               NULL AS subject
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
        students=students, classes=classes, outcomes=outcomes,
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

    c.execute("SELECT subject_id, subject_name FROM subjects ORDER BY subject_name")
    subjects = c.fetchall()
    c.execute("SELECT stage_name FROM stages ORDER BY stage_id")
    stages = [r[0] for r in c.fetchall()]

    conn.close()
    return render_template('student_progress.html',
        student=student,
        outcome_list=outcome_list,
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
               COUNT(DISTINCT a.student_id) AS student_count,
               COUNT(a.attempt_id) AS attempt_count
        FROM classes c
        JOIN subjects subj ON c.subject_id = subj.subject_id
        LEFT JOIN attempts a ON c.class_id = a.class_id
        GROUP BY c.class_id
        ORDER BY subj.subject_name, c.year_group
    """)
    classes = c.fetchall()

    c.execute("""
        SELECT s.student_id,
               s.first_name || ' ' || s.last_name AS name,
               COUNT(DISTINCT a.attempt_id) AS attempt_count
        FROM students s
        LEFT JOIN attempts a ON s.student_id = a.student_id
        GROUP BY s.student_id
        ORDER BY s.last_name, s.first_name
    """)
    students = c.fetchall()
    conn.close()

    return render_template('analytics.html', classes=classes, students=students)


@app.route('/analytics/class/<int:class_id>')
def class_analytics(class_id):
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        SELECT c.class_id,
               subj.subject_name || ' ' || c.year_group AS class_name
        FROM classes c
        JOIN subjects subj ON c.subject_id = subj.subject_id
        WHERE c.class_id = ?
    """, (class_id,))
    class_info = c.fetchone()
    if not class_info:
        conn.close()
        return "Class not found", 404

    c.execute("""
        SELECT s.student_id,
               s.first_name || ' ' || s.last_name AS student_name,
               o.outcome_id, o.outcome_code, o.outcome_name,
               AVG(sd.score) AS avg_score,
               COUNT(sd.score) AS attempt_count
        FROM scoring_detail sd
        JOIN attempt_outcomes ao ON sd.attempt_outcome_id = ao.attempt_outcome_id
        JOIN outcomes o ON ao.outcome_id = o.outcome_id
        JOIN attempts a ON ao.attempt_id = a.attempt_id
        JOIN students s ON a.student_id = s.student_id
        WHERE a.class_id = ?
        GROUP BY s.student_id, o.outcome_id
        ORDER BY o.outcome_code, s.last_name, s.first_name
    """, (class_id,))
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
    )


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


if __name__ == '__main__':
    init_db()
    seed_db()
    app.run(debug=True)
