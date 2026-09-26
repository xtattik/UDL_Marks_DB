# Foundations: Code Split and Database Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 1,700-line `app.py` into a tested `udl/` package with no behaviour change, then add a database layer that is safe on a shared network drive.

**Architecture:** Snapshot ("characterisation") tests are written against the current app first. A one-off script then moves the route code into three Flask blueprints, and the snapshots prove nothing changed. After that the database layer gains network-safe connection settings, versioned migrations, a `live_attempts` view that every report reads from, a startup location check, and an explicit create-database confirmation.

**Tech Stack:** Python 3.12+ (dev machine has 3.14), Flask 3.1, SQLite (stdlib `sqlite3`), pytest, pyflakes.

**Spec:** `docs/superpowers/specs/2026-09-26-multi-teacher-foundations-design.md`. This plan covers build-order stages 1–2 (spec sections 2, 3, and the related parts of 7 and 8). Backups, logins and editing get their own plans, written after this one lands.

**Conventions for every task:**
- Run all commands from the repo root `C:\Code Projects\UDL-Marks-DB` in Git Bash.
- `python -m pytest` runs the whole suite (about 10 s). Run it in full at the end of each task, not just the new test.
- Commit messages end with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## File map (end state of this plan)

| Path | Responsibility |
|---|---|
| `app.py` | Thin entry point: `app = create_app()`, then `app.run()` |
| `udl/__init__.py` | `create_app(db_path=None, create_if_missing=False)`: config, blueprints, error handlers, database-state gate |
| `udl/db.py` | `connect`, `get_db_connection`, migrations (`migrate`, `MIGRATIONS`), `create_blank_database`, `all_classes`, `class_label_sql` |
| `udl/location.py` | `resolve_unc`, `unsafe_location_reason`: refuses OneDrive/WebDAV database locations |
| `udl/scoring.py` | `MAX_SCORE`, `DISCREPANCY_THRESHOLD`, `BANDS`, `score_band`, `sparkline_svg` |
| `udl/grade_scale.py` | Moved unchanged from `utils/grade_scale.py` (letter-grade map, currently unused) |
| `udl/demo.py` | `seed_demo(db_path)`, plus the `python -m udl.demo` CLI for loading demo data |
| `udl/analytics.py` | Blueprint `analytics`: `/`, `/history`, `/student/<id>`, `/analytics`, `/analytics/class/<id>`, `/student/<id>/export` |
| `udl/entry.py` | Blueprint `entry`: `/marks/new`, `/marks/bulk`, `/marks/import`, `/api/students_by_class`, `/api/outcomes` |
| `udl/admin.py` | Blueprint `admin`: everything under `/settings` |
| `templates/error.html` | Friendly error page (DB busy, unsafe location, bad input, 500) |
| `templates/create_database.html` | "No database found — create one?" confirmation |
| `tests/conftest.py`, `tests/helpers.py` | Fixtures (`db_path`, `app`, `client`), demo attempts, query helper |
| `tests/test_characterisation.py` + `tests/snapshots/` | Page-output snapshots for every GET route |
| `tests/test_post_flows.py` | Behaviour of every form POST |
| `tests/test_db_layer.py`, `tests/test_migrations.py`, `tests/test_location.py`, `tests/test_app_states.py`, `tests/test_release.py` | New behaviour |
| `tests/fixtures/legacy_v0.sqlite` | Copy of the pre-change demo database, used for upgrade tests |

Deleted: `utils/assessment_importer.py` (unused) and the `utils/` folder.

---

### Task 1: Test harness

**Files:**
- Create: `requirements-dev.txt`, `pytest.ini`, `tests/helpers.py`, `tests/conftest.py`, `tests/test_smoke.py`

- [ ] **Step 1: Add dev requirements and pytest config**

`requirements-dev.txt`:
```
-r requirements.txt
pytest
pyflakes
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
```

Run: `python -m pip install -r requirements-dev.txt`
Expected: ends with "Successfully installed …" or "Requirement already satisfied".

- [ ] **Step 2: Write the helpers module**

`tests/helpers.py`:
```python
"""Shared test helpers: direct SQL access and a fixed set of demo attempts."""
import sqlite3

# (attempt_id, student_id, (subject, year) or None for cross-curricular, date, title, [(outcome_code, score)])
DEMO_ATTEMPTS = [
    (1, 10001, ('Science', 'Year 7'), '2026-03-02', 'Observation Prac', [('SC4-WS-01', 7), ('SC4-WS-02', 9)]),
    (2, 10001, ('Science', 'Year 7'), '2026-05-11', 'Pendulum Investigation', [('SC4-WS-01', 12), ('SC4-WS-03', 10)]),
    (3, 10002, ('Science', 'Year 7'), '2026-03-02', 'Observation Prac', [('SC4-WS-01', 4), ('SC4-WS-02', 6)]),
    (4, 10003, None, '2026-04-20', 'STEM Day', [('SC4-WS-05', 13)]),
    (5, 10011, ('Science', 'Year 9'), '2026-03-09', 'Evolution Task', [('SC5-GEV-01', 11), ('SC5-WS-04', 8)]),
    (6, 10011, ('Science', 'Year 9'), '2026-06-01', 'Evolution Retest', [('SC5-GEV-01', 16)]),
]


def q(db_path, sql, args=()):
    """Run one query against the test database and return all rows as tuples."""
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def class_id(db_path, subject, year):
    return q(db_path, """
        SELECT c.class_id FROM classes c JOIN subjects s ON s.subject_id = c.subject_id
        WHERE s.subject_name = ? AND c.year_group = ?
    """, (subject, year))[0][0]


def outcome_id(db_path, code):
    return q(db_path, "SELECT outcome_id FROM outcomes WHERE outcome_code = ?", (code,))[0][0]


def add_demo_attempts(db_path):
    """Insert DEMO_ATTEMPTS with raw SQL so the data is identical before and after refactors."""
    conn = sqlite3.connect(db_path)
    for aid, sid, cls, day, title, scores in DEMO_ATTEMPTS:
        cid = class_id(db_path, *cls) if cls else None
        conn.execute(
            "INSERT INTO attempts (attempt_id, student_id, class_id, attempt_date, assessment_title) "
            "VALUES (?, ?, ?, ?, ?)", (aid, sid, cid, day, title))
        for code, score in scores:
            cur = conn.execute("INSERT INTO attempt_outcomes (attempt_id, outcome_id) VALUES (?, ?)",
                               (aid, outcome_id(db_path, code)))
            conn.execute("INSERT INTO scoring_detail (attempt_outcome_id, score) VALUES (?, ?)",
                         (cur.lastrowid, score))
    conn.commit()
    conn.close()
```

- [ ] **Step 3: Write the fixtures (against today's `app.py`)**

`tests/conftest.py`:
```python
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from helpers import add_demo_attempts  # noqa: E402


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / 'test.sqlite')


@pytest.fixture
def app(db_path, monkeypatch):
    import app as legacy
    monkeypatch.setattr(legacy, 'DATABASE', db_path)
    legacy.init_db()
    legacy.seed_db()
    legacy.init_db()  # second pass derives class enrolments, as a real restart did
    add_demo_attempts(db_path)
    legacy.app.config['TESTING'] = True
    return legacy.app


@pytest.fixture
def client(app):
    return app.test_client()
```

- [ ] **Step 4: Write a smoke test**

`tests/test_smoke.py`:
```python
from helpers import q


def test_demo_database_is_populated(client, db_path):
    assert q(db_path, "SELECT COUNT(*) FROM students")[0][0] == 20
    assert q(db_path, "SELECT COUNT(*) FROM attempts")[0][0] == 6
    assert q(db_path, "SELECT COUNT(*) FROM student_classes")[0][0] > 0
    assert client.get('/').status_code == 200
```

- [ ] **Step 5: Run it**

Run: `python -m pytest -v`
Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add requirements-dev.txt pytest.ini tests/
git commit -m "test: add pytest harness with demo data fixtures"
```

---

### Task 2: Snapshot tests for every GET route

**Files:**
- Create: `tests/test_characterisation.py`, `tests/snapshots/*.txt` (generated), `.gitattributes`

- [ ] **Step 1: Write the snapshot test**

`tests/test_characterisation.py`:
```python
"""Characterisation tests: every GET page must render exactly as it did before refactoring.

Regenerate snapshots only when a page is *meant* to change:
    UPDATE_SNAPSHOTS=1 python -m pytest tests/test_characterisation.py
"""
import os
from datetime import date
from pathlib import Path

import pytest

SNAP_DIR = Path(__file__).parent / 'snapshots'
UPDATE = os.environ.get('UPDATE_SNAPSHOTS') == '1'

# Class ids follow the demo seed order: Maths Y7=1, Maths Y9=2, Science Y7=3, Science Y9=4, English Y7=5, English Y9=6.
GET_ROUTES = [
    ('home', '/'),
    ('marks_new', '/marks/new'),
    ('marks_bulk', '/marks/bulk'),
    ('marks_import', '/marks/import'),
    ('history', '/history'),
    ('student_10001', '/student/10001'),
    ('student_10001_science', '/student/10001?subject_id=2'),
    ('student_10011_stage5', '/student/10011?stage=Stage+5'),
    ('student_export_10001', '/student/10001/export'),
    ('analytics', '/analytics'),
    ('class_3_peak', '/analytics/class/3'),
    ('class_3_avg', '/analytics/class/3?view=avg'),
    ('class_4_peak', '/analytics/class/4'),
    ('settings', '/settings'),
    ('students', '/settings/students'),
    ('students_search', '/settings/students?q=Sm&year=Year+7'),
    ('student_new', '/settings/students/new'),
    ('student_edit', '/settings/student/10001/edit'),
    ('students_import', '/settings/students/import'),
    ('classes', '/settings/classes'),
    ('subjects', '/settings/subjects'),
    ('roster_3', '/settings/class/3/roster'),
    ('roster_3_search', '/settings/class/3/roster?q=Gar'),
    ('outcomes', '/settings/outcomes'),
    ('outcomes_unset', '/settings/outcomes?unset=1'),
    ('enrolments_import', '/settings/enrollments/import'),
    ('api_students_by_class', '/api/students_by_class?class_id=3'),
    ('api_outcomes', '/api/outcomes?q=WS'),
]


def normalise(body):
    return body.replace(date.today().isoformat(), '<TODAY>')


@pytest.mark.parametrize('name,url', GET_ROUTES, ids=[n for n, _ in GET_ROUTES])
def test_page_matches_snapshot(client, name, url):
    resp = client.get(url)
    assert resp.status_code == 200
    body = normalise(resp.get_data(as_text=True))
    snap = SNAP_DIR / f'{name}.txt'
    if UPDATE:
        SNAP_DIR.mkdir(exist_ok=True)
        with open(snap, 'w', encoding='utf-8', newline='') as f:
            f.write(body)
        return
    assert snap.exists(), f'Missing snapshot {snap.name}; run with UPDATE_SNAPSHOTS=1'
    with open(snap, encoding='utf-8', newline='') as f:
        assert body == f.read()
```

`.gitattributes`:
```
tests/snapshots/*.txt -text
```

- [ ] **Step 2: Run without snapshots to confirm the test fails**

Run: `python -m pytest tests/test_characterisation.py -q`
Expected: 28 failed, each with "Missing snapshot".

- [ ] **Step 3: Generate the snapshots, then prove they're stable**

Run: `UPDATE_SNAPSHOTS=1 python -m pytest tests/test_characterisation.py -q`, then `python -m pytest tests/test_characterisation.py -q`
Expected: both report `28 passed`. If the second run fails, the page contains something time-dependent beyond today's date. Add a `.replace(...)` for it in `normalise()` and regenerate.

- [ ] **Step 4: Sanity-check the snapshots contain real data**

Run: `grep -l "Pendulum Investigation" tests/snapshots/*.txt`
Expected: lists at least `history.txt`, `student_10001.txt`, `student_export_10001.txt`.

- [ ] **Step 5: Commit**

```bash
git add .gitattributes tests/test_characterisation.py tests/snapshots/
git commit -m "test: snapshot every GET page before refactoring"
```

---

### Task 3: Behaviour tests for every form POST

**Files:**
- Create: `tests/test_post_flows.py`

- [ ] **Step 1: Write the tests**

`tests/test_post_flows.py`:
```python
import io

from helpers import class_id, outcome_id, q

SCORES_SQL = """
    SELECT a.student_id, sd.score FROM attempts a
    JOIN attempt_outcomes ao ON ao.attempt_id = a.attempt_id
    JOIN scoring_detail sd ON sd.attempt_outcome_id = ao.attempt_outcome_id
    WHERE a.assessment_title = ? ORDER BY a.student_id
"""


def csv_upload(text, name='upload.csv'):
    return (io.BytesIO(text.encode('utf-8')), name)


def test_single_entry_saves_and_clamps(client, db_path):
    oid = outcome_id(db_path, 'SC4-WS-04')
    resp = client.post('/marks/new', data={
        'student_id': '10004', 'assessment_title': 'Quiz 1', 'attempt_date': '2026-07-01',
        'class_id': str(class_id(db_path, 'Science', 'Year 7')),
        'outcome_ids': str(oid), f'score_{oid}': '99'})
    assert resp.status_code == 302
    assert q(db_path, SCORES_SQL, ('Quiz 1',)) == [(10004, 16)]


def test_single_entry_without_outcomes_is_rejected(client, db_path):
    resp = client.post('/marks/new', data={
        'student_id': '10004', 'assessment_title': 'Empty', 'attempt_date': '2026-07-01',
        'class_id': '3', 'outcome_ids': ''})
    assert resp.status_code == 400
    assert q(db_path, SCORES_SQL, ('Empty',)) == []


def test_bulk_entry_skips_blank_rows(client, db_path):
    oid = outcome_id(db_path, 'SC4-WS-04')
    resp = client.post('/marks/bulk', data={
        'assessment_title': 'Bulk Quiz', 'attempt_date': '2026-07-02', 'class_id': '3',
        'outcome_ids': str(oid), 'student_ids': '10001,10002',
        f's10001o{oid}': '8', f's10002o{oid}': ''})
    assert resp.status_code == 200
    assert q(db_path, SCORES_SQL, ('Bulk Quiz',)) == [(10001, 8)]


def test_csv_import_rounds_scores_and_reports_unknown_students(client, db_path):
    text = ("Name,Student ID,SC4-WS-04 Processing,Scale Average,Comment\n"
            "Alex Smith,10001,9.6,9,Good work\n"
            "Nobody,99999,5,5,\n")
    resp = client.post('/marks/import', content_type='multipart/form-data', data={
        'assessment_title': 'Imported Task', 'attempt_date': '2026-07-03', 'class_id': '3',
        'csv_file': csv_upload(text)})
    assert resp.status_code == 200
    assert q(db_path, SCORES_SQL, ('Imported Task',)) == [(10001, 10)]
    assert 'not found in database' in resp.get_data(as_text=True)


def test_new_student_then_duplicate_id(client, db_path):
    form = {'student_id': '20001', 'first_name': 'Robin', 'last_name': 'Lee', 'year_group': 'Year 8'}
    assert client.post('/settings/students/new', data=form).status_code == 302
    assert q(db_path, "SELECT first_name, last_name, year_group FROM students WHERE student_id = 20001") \
        == [('Robin', 'Lee', 'Year 8')]
    assert 'already exists' in client.post('/settings/students/new', data=form).get_data(as_text=True)


def test_edit_student(client, db_path):
    resp = client.post('/settings/student/10001/edit',
                       data={'first_name': 'Alexis', 'last_name': 'Smith', 'year_group': 'Year 8'})
    assert resp.status_code == 302
    assert q(db_path, "SELECT first_name, year_group FROM students WHERE student_id = 10001") \
        == [('Alexis', 'Year 8')]


def test_student_csv_import_upserts_and_normalises_year(client, db_path):
    text = "student_id,first_name,last_name,year_group\n10001,Alexandra,Smith,7\n20002,New,Kid,8\n"
    resp = client.post('/settings/students/import', content_type='multipart/form-data',
                       data={'csv_file': csv_upload(text)})
    assert resp.status_code == 200
    assert q(db_path, "SELECT student_id, first_name, year_group FROM students "
                      "WHERE student_id IN (10001, 20002) ORDER BY student_id") \
        == [(10001, 'Alexandra', 'Year 7'), (20002, 'New', 'Year 8')]


def test_add_class_with_code_and_update_code(client, db_path):
    sci = q(db_path, "SELECT subject_id FROM subjects WHERE subject_name = 'Science'")[0][0]
    client.post('/settings/classes', data={'action': 'add', 'subject_id': str(sci),
                                           'year_group': 'Year 8', 'class_code': '8S'})
    rows = q(db_path, "SELECT class_id, class_code FROM classes WHERE year_group = 'Year 8'")
    assert [r[1] for r in rows] == ['8S']
    client.post('/settings/classes', data={'action': 'update_code', 'class_id': str(rows[0][0]),
                                           'class_code': '8T'})
    assert q(db_path, "SELECT class_code FROM classes WHERE class_id = ?", (rows[0][0],)) == [('8T',)]


def test_add_subject_and_reject_duplicate(client, db_path):
    client.post('/settings/subjects', data={'subject_name': 'Drama'})
    assert q(db_path, "SELECT COUNT(*) FROM subjects WHERE subject_name = 'Drama'") == [(1,)]
    assert 'already exists' in client.post('/settings/subjects', data={'subject_name': 'Drama'}) \
        .get_data(as_text=True)


def test_roster_add_and_remove(client, db_path):
    enrolled = "SELECT COUNT(*) FROM student_classes WHERE student_id = 10006 AND class_id = 3"
    client.post('/settings/class/3/roster', data={'action': 'add', 'student_id': '10006'})
    assert q(db_path, enrolled) == [(1,)]
    client.post('/settings/class/3/roster', data={'action': 'remove', 'student_id': '10006'})
    assert q(db_path, enrolled) == [(0,)]


def test_outcome_add_and_update(client, db_path):
    client.post('/settings/outcomes', data={'action': 'add', 'outcome_code': 'sc4-new-01',
                                            'outcome_name': 'New outcome', 'is_theoretical': '0',
                                            'subject_id': '', 'stage_id': ''})
    oid, subj = q(db_path, "SELECT outcome_id, subject_id FROM outcomes WHERE outcome_code = 'SC4-NEW-01'")[0]
    assert subj is None
    client.post('/settings/outcomes', data={'action': 'update', 'outcome_id': str(oid),
                                            'subject_id': '2', 'stage_id': '2'})
    assert q(db_path, "SELECT subject_id, stage_id FROM outcomes WHERE outcome_id = ?", (oid,)) == [(2, 2)]


def test_enrolment_import_creates_subject_and_class(client, db_path):
    text = "student_id,subject_name,year_group,class_code\n10006,PDHPE,8,8P\n10006,PDHPE,8,8P\n"
    resp = client.post('/settings/enrollments/import', content_type='multipart/form-data',
                       data={'csv_file': csv_upload(text)})
    assert resp.status_code == 200
    rows = q(db_path, """
        SELECT s.subject_name, c.year_group, c.class_code FROM student_classes sc
        JOIN classes c ON c.class_id = sc.class_id JOIN subjects s ON s.subject_id = c.subject_id
        WHERE sc.student_id = 10006 AND s.subject_name = 'PDHPE'""")
    assert rows == [('PDHPE', 'Year 8', '8P')]
    assert 'Already enrolled' in resp.get_data(as_text=True)
```

- [ ] **Step 2: Run them**

Run: `python -m pytest tests/test_post_flows.py -v`
Expected: `12 passed`. These describe current behaviour, so they should pass straight away. If one fails, the test has misread current behaviour. Fix the **test** to match the app (the goal is a faithful record), then re-run.

- [ ] **Step 3: Commit**

```bash
git add tests/test_post_flows.py
git commit -m "test: cover every form POST before refactoring"
```

---

### Task 4: Split `app.py` into the `udl/` package

**Files:**
- Create: `udl/__init__.py`, and (generated) `udl/db.py`, `udl/scoring.py`, `udl/demo.py`, `udl/analytics.py`, `udl/entry.py`, `udl/admin.py`
- Move: `utils/grade_scale.py` → `udl/grade_scale.py`
- Delete: `utils/assessment_importer.py`
- Modify: `app.py` (rewritten), `templates/*.html` (endpoint names), `tests/conftest.py`

The split is done by a one-off script so the move is exact and repeatable. The script checks every line boundary before it writes anything.

- [ ] **Step 1: Confirm `app.py` is at the expected revision**

Run: `grep -n "^def \|^@app.route" app.py | head -3`
Expected:
```
25:def _score_band(score):
35:def get_db_connection():
42:def init_db():
```
If the numbers differ, stop. The line ranges below would be wrong.

- [ ] **Step 2: Create the split script**

`split_app.py` (repo root; deleted in Step 5):
```python
"""One-off: split app.py into the udl/ package. Run once from the repo root, then delete."""
import re
from pathlib import Path

SRC = Path('app.py').read_text(encoding='utf-8').splitlines(keepends=True)


def take(first, last):
    return ''.join(SRC[first - 1:last])


def expect(line_no, prefix):
    actual = SRC[line_no - 1].strip()
    assert actual.startswith(prefix), f'line {line_no}: expected {prefix!r}, got {actual!r}'


ENDPOINTS = {
    'index': 'analytics.index', 'recent_entries': 'analytics.recent_entries',
    'student_progress': 'analytics.student_progress', 'analytics': 'analytics.analytics',
    'class_analytics': 'analytics.class_analytics', 'student_export': 'analytics.student_export',
    'marks_entry': 'entry.marks_entry', 'bulk_entry': 'entry.bulk_entry',
    'import_marks': 'entry.import_marks', 'api_students_by_class': 'entry.api_students_by_class',
    'api_outcomes': 'entry.api_outcomes',
    'settings': 'admin.settings', 'manage_students': 'admin.manage_students',
    'new_student': 'admin.new_student', 'edit_student': 'admin.edit_student',
    'import_students': 'admin.import_students', 'manage_classes': 'admin.manage_classes',
    'manage_subjects': 'admin.manage_subjects', 'class_roster': 'admin.class_roster',
    'manage_outcomes': 'admin.manage_outcomes', 'import_enrollments': 'admin.import_enrollments',
}

ROUTES = {
    'analytics': [(374, 412), (500, 534), (535, 689), (690, 752), (846, 939), (1643, 1709)],
    'entry': [(413, 499), (753, 845), (940, 1072), (1329, 1347), (1492, 1518)],
    'admin': [(1073, 1084), (1085, 1118), (1119, 1153), (1154, 1187), (1188, 1255),
              (1256, 1305), (1306, 1328), (1348, 1409), (1410, 1491), (1519, 1642)],
}

HEADERS = {
    'analytics': '''"""Read-only views: dashboard, history, analytics, class heatmap, student progress, export."""
import csv
import io
from datetime import date

from flask import Blueprint, Response, render_template, request

from .db import all_classes, get_db_connection
from .scoring import BANDS, DISCREPANCY_THRESHOLD, MAX_SCORE, score_band, sparkline_svg

bp = Blueprint('analytics', __name__)
''',
    'entry': '''"""Mark entry: single entry, bulk grid, CSV import, and the JSON helpers those forms use."""
import csv
import io
from datetime import date

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from .db import get_db_connection
from .scoring import MAX_SCORE

bp = Blueprint('entry', __name__)
''',
    'admin': '''"""Settings: students, classes, rosters, enrolment import, subjects and outcomes."""
import csv
import io
import sqlite3
from datetime import date

from flask import Blueprint, redirect, render_template, request, url_for

from .db import all_classes, get_db_connection

bp = Blueprint('admin', __name__)
''',
}


def rename(code):
    code = code.replace('@app.route(', '@bp.route(')
    for old, new in (('_score_band(', 'score_band('), ('_sparkline_svg(', 'sparkline_svg('),
                     ('_all_classes(', 'all_classes(')):
        code = code.replace(old, new)
    return re.sub(r"url_for\((['\"])(\w+)\1",
                  lambda m: 'url_for({q}{n}{q}'.format(q=m.group(1), n=ENDPOINTS.get(m.group(2), m.group(2))),
                  code)


# ── Boundary checks ──────────────────────────────────────────────────────────
covered = set()
for ranges in ROUTES.values():
    for first, last in ranges:
        expect(first, '@app.route(')
        covered.update(range(first, last + 1))
assert covered == set(range(374, 1710)), 'route ranges must cover lines 374-1709 exactly once'
expect(1710, "if __name__ == '__main__':")
expect(12, 'MAX_SCORE = 16'); expect(25, 'def _score_band'); expect(328, 'def _sparkline_svg')
expect(43, 'conn = get_db_connection()'); expect(240, 'conn.close()')
expect(354, 'def _all_classes'); expect(369, 'return cursor.fetchall()')
expect(244, 'conn = get_db_connection()'); expect(245, 'c = conn.cursor()')
expect(323, 'c.execute("INSERT OR IGNORE INTO _meta'); expect(325, 'conn.close()')

out = Path('udl')
out.mkdir(exist_ok=True)

# ── scoring.py ───────────────────────────────────────────────────────────────
(out / 'scoring.py').write_text(
    '"""Score bands and small presentation helpers for 0–16 outcome scores."""\n\n\n'
    + rename(take(12, 33)).rstrip() + '\n\n\n' + rename(take(328, 349)).rstrip() + '\n',
    encoding='utf-8')

# ── db.py ────────────────────────────────────────────────────────────────────
(out / 'db.py').write_text(
    '"""Database access: connections, schema setup and shared query helpers."""\n'
    'import sqlite3\n\n'
    'from flask import current_app\n\n\n'
    'def connect(db_path):\n'
    '    conn = sqlite3.connect(db_path)\n'
    '    conn.row_factory = sqlite3.Row\n'
    '    conn.execute("PRAGMA foreign_keys = ON")\n'
    '    return conn\n\n\n'
    'def get_db_connection():\n'
    "    return connect(current_app.config['DATABASE'])\n\n\n"
    'def init_db(db_path):\n'
    '    conn = connect(db_path)\n'
    + take(44, 240).rstrip() + '\n\n\n'
    + rename(take(354, 369)).rstrip() + '\n',
    encoding='utf-8')

# ── demo.py ──────────────────────────────────────────────────────────────────
ENROL = '''
    # Enrol demo students in their year group's classes (the app used to do this on next start).
    c.execute("""
        INSERT OR IGNORE INTO student_classes (student_id, class_id)
        SELECT s.student_id, c.class_id
        FROM students s
        JOIN classes c ON s.year_group = c.year_group
        WHERE s.year_group IS NOT NULL
    """)
'''
(out / 'demo.py').write_text(
    '"""Demo data for development and tests. Load it with:  python -m udl.demo [db_path]"""\n'
    'from .db import connect, init_db\n\n\n'
    'def seed_demo(db_path):\n'
    '    """Add sample subjects, outcomes, students and classes. Does nothing if already seeded."""\n'
    '    conn = connect(db_path)\n'
    + take(245, 322) + ENROL + take(323, 325).rstrip() + '\n\n\n'
    "if __name__ == '__main__':\n"
    '    import sys\n'
    '    from . import DEFAULT_DB_PATH\n'
    '    path = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_DB_PATH)\n'
    '    init_db(path)\n'
    '    seed_demo(path)\n'
    "    print(f'Demo data loaded into {path}')\n",
    encoding='utf-8')

# ── blueprints ───────────────────────────────────────────────────────────────
for module, ranges in ROUTES.items():
    body = ''.join(rename(take(first, last)) for first, last in ranges)
    (out / f'{module}.py').write_text(HEADERS[module] + '\n\n' + body.rstrip() + '\n', encoding='utf-8')

# ── templates ────────────────────────────────────────────────────────────────
for tpl in Path('templates').glob('*.html'):
    text = tpl.read_text(encoding='utf-8')
    new = rename(text)
    if new != text:
        tpl.write_text(new, encoding='utf-8', newline='')

print('Split complete.')
```

- [ ] **Step 3: Run the script**

Run: `python split_app.py`
Expected: `Split complete.` An `AssertionError` means `app.py` differs from the revision this plan was written against. Stop and report it.

- [ ] **Step 4: Write the package entry point and thin `app.py`**

`udl/__init__.py`:
```python
"""UDL Marks DB application package."""
import os
from pathlib import Path

from flask import Flask

from . import db

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / 'udl_marks_db.sqlite'


def create_app(db_path=None):
    app = Flask(__name__, template_folder=str(ROOT / 'templates'))
    app.config['DATABASE'] = str(db_path or os.environ.get('UDL_DB_PATH') or DEFAULT_DB_PATH)

    db.init_db(app.config['DATABASE'])

    from .admin import bp as admin_bp
    from .analytics import bp as analytics_bp
    from .entry import bp as entry_bp
    app.register_blueprint(analytics_bp)
    app.register_blueprint(entry_bp)
    app.register_blueprint(admin_bp)
    return app
```

`app.py` (replace the whole file):
```python
"""Start UDL Marks DB on this computer. The application itself lives in the udl/ package."""
import os

from udl import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=os.environ.get("UDL_DEBUG") == "1")
```

- [ ] **Step 5: Move/delete the old utils and the script**

```bash
git mv utils/grade_scale.py udl/grade_scale.py
git rm -q utils/assessment_importer.py
rm -f split_app.py
rm -rf utils
```

- [ ] **Step 6: Point the test fixture at the new package**

In `tests/conftest.py`, replace the whole `app` fixture with:
```python
@pytest.fixture
def app(db_path):
    from udl import create_app
    from udl.demo import seed_demo
    application = create_app(db_path)
    seed_demo(db_path)
    add_demo_attempts(db_path)
    application.config['TESTING'] = True
    return application
```

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest -q`
Expected: `41 passed` (1 smoke + 28 snapshots + 12 POST). A snapshot failure means the split changed output. Diff the page against its snapshot and fix the **code**, never the snapshot.

- [ ] **Step 8: Check for undefined or unused names**

Run: `python -m pyflakes app.py udl`
Expected: no output. If pyflakes reports an unused import in a generated header, delete that import. If it reports an undefined name, add the import to that module's header.

- [ ] **Step 9: Check nothing still references old endpoint names**

Run: `grep -rnE "url_for\('(index|marks_entry|settings|analytics|manage_students)'" templates udl || echo clean`
Expected: `clean`.

- [ ] **Step 10: Commit**

```bash
git add -A app.py udl templates tests
git status --short   # expect: app.py, udl/*, templates/*, tests/conftest.py, utils/ removals only
git commit -m "refactor: split app.py into udl package with blueprints (no behaviour change)"
```

---

### Task 5: One class-label helper, fixing missing class codes

Home, History and Analytics show "Science Year 9" for both 9.1 and 9.2, because three queries omit `class_code`. Eight other queries repeat the correct expression.

**Files:**
- Modify: `udl/db.py`, `udl/analytics.py`, `udl/entry.py`, `udl/admin.py`
- Test: `tests/test_class_labels.py`

- [ ] **Step 1: Write the failing test**

`tests/test_class_labels.py`:
```python
import sqlite3

import pytest


@pytest.fixture
def coded_client(client, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE classes SET class_code = '7S' WHERE class_id = 3")
    conn.commit()
    conn.close()
    return client


# Each assertion targets the markup of the buggy list itself (not other lists on the page
# that already include the code), so it fails before the fix.

def test_history_shows_class_code(coded_client):
    assert '&#127891; Science Year 7 (7S)' in coded_client.get('/history').get_data(as_text=True)


def test_analytics_shows_class_code(coded_client):
    text = coded_client.get('/analytics').get_data(as_text=True)
    assert '<div class="cc-name">Science Year 7 (7S)</div>' in text


def test_home_recent_entries_show_class_code(coded_client):
    text = coded_client.get('/').get_data(as_text=True)
    assert '<span class="badge">Science Year 7 (7S)</span>' in text
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_class_labels.py -v`
Expected: 3 FAILED.

- [ ] **Step 3: Add the helper**

Append to `udl/db.py`:
```python


def class_label_sql(cls='c', subj='subj'):
    """SQL expression for a class's display name, e.g. 'Science Year 9 (9.1)'.

    `cls` and `subj` are the table aliases used in the calling query.
    """
    return (f"{subj}.subject_name || ' ' || {cls}.year_group || "
            f"CASE WHEN {cls}.class_code IS NOT NULL AND {cls}.class_code != '' "
            f"THEN ' (' || {cls}.class_code || ')' ELSE '' END")
```

- [ ] **Step 4: Use it in all eleven places**

In each query below, turn the SQL string into an f-string (`"""` → `f"""`; the SQL contains no `{` or `}`), and replace the class-name expression as shown. Add `class_label_sql` to each module's `from .db import …` line.

Three buggy queries, missing the code:
- `udl/analytics.py`, `index()`: `subj.subject_name || ' ' || c.year_group AS class_name` → `{class_label_sql('c')} AS class_name`
- `udl/analytics.py`, `recent_entries()`: `subj.subject_name || ' ' || cl.year_group AS class_name,` → `{class_label_sql('cl')} AS class_name,`
- `udl/analytics.py`, `analytics()`: `subj.subject_name || ' ' || c.year_group AS class_name,` → `{class_label_sql('c')} AS class_name,`

Eight duplicated full expressions. Replace the three lines
```sql
               subj.subject_name || ' ' || c.year_group ||
                   CASE WHEN c.class_code IS NOT NULL AND c.class_code != ''
                        THEN ' (' || c.class_code || ')' ELSE '' END AS class_name
```
with `               {class_label_sql('c')} AS class_name` (keep any trailing comma), in:
- `udl/db.py`, `all_classes()`
- `udl/entry.py`: `marks_entry()`, `bulk_entry()`, `import_marks()`
- `udl/analytics.py`: `class_analytics()`
- `udl/admin.py`: `class_roster()`

In `udl/analytics.py` `student_progress()` and `student_export()`, the expression sits inside a `CASE … ELSE 'Cross-curricular' END` using alias `cl`. Replace only the inner three lines
```sql
                       subj.subject_name || ' ' || cl.year_group ||
                       CASE WHEN cl.class_code IS NOT NULL AND cl.class_code != ''
                            THEN ' (' || cl.class_code || ')' ELSE '' END
```
with `                       {class_label_sql('cl')}`.

- [ ] **Step 5: Verify no copies remain**

Run: `grep -rn "subject_name || ' ' ||" udl`
Expected: exactly one match, inside `class_label_sql` in `udl/db.py`.

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest -q && python -m pyflakes udl`
Expected: `44 passed`, no pyflakes output. Demo classes have no codes, so snapshots are unchanged.

- [ ] **Step 7: Commit**

```bash
git add udl tests/test_class_labels.py
git commit -m "fix: show class codes on home, history and analytics via one class-label helper"
```

---

### Task 6: Keep the release build and clean-DB script working

**Files:**
- Modify: `build_release.bat`, `make_clean_db.py`, `README.md`
- Test: `tests/test_release.py`

- [ ] **Step 1: Write the failing test**

`tests/test_release.py`:
```python
import subprocess
import sys
from pathlib import Path

from helpers import q

ROOT = Path(__file__).resolve().parent.parent


def test_make_clean_db_creates_empty_structured_database(tmp_path):
    target = tmp_path / 'clean.sqlite'
    subprocess.run([sys.executable, str(ROOT / 'make_clean_db.py'), str(target)],
                   check=True, cwd=tmp_path)
    assert q(str(target), "SELECT COUNT(*) FROM stages") == [(3,)]
    assert q(str(target), "SELECT COUNT(*) FROM students") == [(0,)]
    assert q(str(target), "SELECT value FROM _meta WHERE key = 'seeded'") == [('true',)]


def test_release_build_copies_the_package():
    script = (ROOT / 'build_release.bat').read_text(encoding='utf-8')
    assert 'xcopy /e /i /q /y udl' in script
    assert '-m pip install -r requirements.txt' in script
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_release.py -v`
Expected: both FAIL. `make_clean_db.py` imports `app` internals that no longer exist, and the bat file lacks the lines.

- [ ] **Step 3: Rewrite `make_clean_db.py`**

```python
"""
Creates a clean distribution database.
Schema + stage/year structure only — no sample subjects, students, or outcomes.
The 'seeded' flag prevents sample data loading.

Usage: python make_clean_db.py [output_path]
"""
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from udl import db  # noqa: E402

db_path = sys.argv[1] if len(sys.argv) > 1 else 'udl_marks_db.sqlite'

if os.path.exists(db_path):
    os.remove(db_path)

db.init_db(db_path)

conn = sqlite3.connect(db_path)
conn.execute("INSERT OR IGNORE INTO _meta (key, value) VALUES ('seeded', 'true')")
conn.commit()
conn.close()

print(f"Clean database created: {db_path}")
```

- [ ] **Step 4: Update `build_release.bat`**

Replace the step-4 install line
```bat
"%DIST_DIR%\python\python.exe" -m pip install flask --no-warn-script-location -q
```
with
```bat
"%DIST_DIR%\python\python.exe" -m pip install -r requirements.txt --no-warn-script-location -q
```
and change its echo to `echo [4/7] Installing dependencies...`.

In step 5, after `copy /y app.py …`, add:
```bat
xcopy /e /i /q /y udl "%DIST_DIR%\udl" > nul
if exist "%DIST_DIR%\udl\__pycache__" rmdir /s /q "%DIST_DIR%\udl\__pycache__"
```

- [ ] **Step 5: Add a developer section to `README.md`**

Append:
```markdown

## Development

- Run locally: double-click `run.bat` (debug mode on), or `python app.py`.
- Load demo data into a database: `python -m udl.demo [path-to.sqlite]`.
- Tests: `python -m pip install -r requirements-dev.txt`, then `python -m pytest`.
- Page snapshots live in `tests/snapshots/`. Regenerate them only when a page is meant to change:
  `UPDATE_SNAPSHOTS=1 python -m pytest tests/test_characterisation.py`.
- Code layout: `app.py` starts the app; everything else is in `udl/` (one blueprint per area).
```

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest -q`
Expected: `46 passed`.

- [ ] **Step 7: Commit**

```bash
git add make_clean_db.py build_release.bat README.md tests/test_release.py
git commit -m "build: package udl/ in releases; make_clean_db uses the new db module"
```

---

### Task 7: Network-safe connection settings

**Files:**
- Modify: `udl/db.py` (`connect`, `get_db_connection`), `udl/__init__.py`
- Test: `tests/test_db_layer.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_db_layer.py`:
```python
import sqlite3
import threading
import time

import pytest

from helpers import q
from udl.db import connect, get_db_connection


def test_connection_uses_network_safe_settings(app):
    with app.app_context():
        conn = get_db_connection()
        try:
            assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
            assert conn.execute('PRAGMA synchronous').fetchone()[0] == 2  # FULL
            assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
            assert conn.execute('PRAGMA busy_timeout').fetchone()[0] == 10000
        finally:
            conn.close()


def test_second_writer_waits_for_first_then_succeeds(app, db_path):
    locked = threading.Event()

    def hold_write_lock():
        blocker = connect(db_path)
        blocker.execute("INSERT INTO subjects (subject_name) VALUES ('Blocker')")
        locked.set()
        time.sleep(0.3)
        blocker.commit()
        blocker.close()

    t = threading.Thread(target=hold_write_lock)
    t.start()
    assert locked.wait(2)
    writer = connect(db_path, busy_timeout_ms=5000)
    writer.execute("INSERT INTO subjects (subject_name) VALUES ('Waiter')")
    writer.commit()
    writer.close()
    t.join()
    names = {r[0] for r in q(db_path, "SELECT subject_name FROM subjects")}
    assert {'Blocker', 'Waiter'} <= names


def test_writer_gives_up_after_busy_timeout(app, db_path):
    blocker = connect(db_path)
    blocker.execute("INSERT INTO subjects (subject_name) VALUES ('Blocker')")
    writer = connect(db_path, busy_timeout_ms=100)
    try:
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            writer.execute("INSERT INTO subjects (subject_name) VALUES ('Too late')")
    finally:
        writer.close()
        blocker.rollback()
        blocker.close()
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_db_layer.py -v`
Expected: `test_connection_uses_network_safe_settings` FAILS (busy_timeout is 5000), and the timeout test fails with `TypeError` (no `busy_timeout_ms` parameter).

- [ ] **Step 3: Implement**

In `udl/db.py`, replace `connect` and `get_db_connection` with:
```python
BUSY_TIMEOUT_MS = 10_000  # how long a save waits for another teacher's save to finish


def connect(db_path, busy_timeout_ms=None):
    """Open the database with settings that are safe on a shared network drive.

    - journal_mode=DELETE: the classic rollback journal. WAL mode is unsafe on network drives.
    - isolation_level='IMMEDIATE': the write lock is taken at the first write in a request
      and held only until commit, so saves are short and never interleave.
    - busy timeout: a second writer waits rather than failing immediately.
    """
    timeout_ms = BUSY_TIMEOUT_MS if busy_timeout_ms is None else busy_timeout_ms
    conn = sqlite3.connect(db_path, timeout=timeout_ms / 1000, isolation_level='IMMEDIATE')
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def get_db_connection():
    return connect(current_app.config['DATABASE'], current_app.config.get('DB_BUSY_TIMEOUT_MS'))
```

In `udl/__init__.py` `create_app`, after setting `app.config['DATABASE']`, add:
```python
    app.config['DB_BUSY_TIMEOUT_MS'] = db.BUSY_TIMEOUT_MS
```

- [ ] **Step 4: Run the whole suite**

Run: `python -m pytest -q`
Expected: `49 passed`.

- [ ] **Step 5: Commit**

```bash
git add udl tests/test_db_layer.py
git commit -m "feat: network-safe SQLite settings (rollback journal, immediate write lock, 10s busy wait)"
```

---

### Task 8: Friendly "not saved" and error pages

**Files:**
- Create: `templates/error.html`
- Modify: `udl/__init__.py`, `udl/entry.py` (`marks_entry` except block)
- Test: `tests/test_db_layer.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db_layer.py`:
```python


def test_locked_database_shows_not_saved_page(app, client, db_path):
    app.config['DB_BUSY_TIMEOUT_MS'] = 100
    blocker = connect(db_path)
    blocker.execute("INSERT INTO subjects (subject_name) VALUES ('Blocker')")
    try:
        resp = client.post('/settings/subjects', data={'subject_name': 'Drama'})
    finally:
        blocker.rollback()
        blocker.close()
    assert resp.status_code == 503
    assert 'not saved' in resp.get_data(as_text=True)
    assert q(db_path, "SELECT COUNT(*) FROM subjects WHERE subject_name = 'Drama'") == [(0,)]


def test_invalid_single_entry_shows_friendly_error(client):
    resp = client.post('/marks/new', data={'assessment_title': 'No student', 'outcome_ids': '1'})
    assert resp.status_code == 400
    text = resp.get_data(as_text=True)
    assert 'Marks not saved' in text
    assert 'Traceback' not in text


def test_unexpected_error_shows_generic_page(app, client, monkeypatch):
    app.config['PROPAGATE_EXCEPTIONS'] = False
    import udl.analytics

    def boom(*args, **kwargs):
        raise RuntimeError('kaboom')
    monkeypatch.setattr(udl.analytics, 'all_classes', boom)
    resp = client.get('/')
    assert resp.status_code == 500
    text = resp.get_data(as_text=True)
    assert 'Something went wrong' in text
    assert 'kaboom' not in text
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_db_layer.py -v`
Expected: the three new tests FAIL.

- [ ] **Step 3: Create the error template**

`templates/error.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} — UDL Marks DB</title>
    <style>
        body { font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa;
               color: #2d3748; margin: 0; padding: 48px 16px; }
        .card { max-width: 640px; margin: 0 auto; background: #fff; border-radius: 10px;
                padding: 28px 32px; box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                border-top: 5px solid #c0392b; }
        h1 { font-size: 1.4rem; margin: 0 0 12px; }
        p { line-height: 1.55; }
        a { color: #2c5282; }
    </style>
</head>
<body>
    <div class="card">
        <h1>{{ title }}</h1>
        <p>{{ message }}</p>
        <p><a href="javascript:history.back()">&larr; Go back</a> &nbsp;·&nbsp; <a href="/">Home</a></p>
    </div>
</body>
</html>
```

- [ ] **Step 4: Register the error handlers**

In `udl/__init__.py` add `import sqlite3` and `render_template` to the Flask import (`from flask import Flask, render_template`). Inside `create_app`, before `return app`, add:
```python
    @app.errorhandler(sqlite3.OperationalError)
    def database_unavailable(err):
        app.logger.error('Database error: %s', err)
        return render_template(
            'error.html', title='Changes not saved',
            message='The database is busy or unreachable, so your changes were not saved. '
                    'Wait a few seconds and try again. If this keeps happening, check that '
                    'this computer can open the shared drive.'), 503

    @app.errorhandler(500)
    def server_error(err):
        return render_template(
            'error.html', title='Something went wrong',
            message='The app hit an unexpected problem and nothing was changed by this request. '
                    'Try again; if it keeps happening, note what you were doing and tell the '
                    'person who looks after UDL Marks DB.'), 500
```

- [ ] **Step 5: Stop `marks_entry` swallowing every error**

In `udl/entry.py` `marks_entry()`, replace the block
```python
        except Exception as e:
            conn.rollback()
            conn.close()
            print(f"marks_entry error: {e}")
            return f"Error saving marks: {e}", 500
```
with
```python
        except (KeyError, ValueError) as e:
            conn.rollback()
            conn.close()
            return render_template(
                'error.html', title='Marks not saved',
                message=f'Part of the form was missing or invalid ({e}). '
                        'Go back, check the entry and try again.'), 400
        except Exception:
            conn.rollback()
            conn.close()
            raise
```

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest -q && python -m pyflakes udl`
Expected: `52 passed`, no pyflakes output.

- [ ] **Step 7: Commit**

```bash
git add templates/error.html udl tests/test_db_layer.py
git commit -m "feat: friendly not-saved, bad-input and error pages instead of raw exceptions"
```

---

### Task 9: Versioned migrations (replacing `init_db`)

Today `init_db` re-runs every schema change and the duplicate-class clean-up on **every** start, with errors silently ignored. It also contains a dangerous `ALTER TABLE attempts DROP COLUMN class_id`, which only fails because of a foreign key. This task replaces it with numbered migrations that each run exactly once.

**Files:**
- Modify: `udl/db.py` (remove `init_db`; add `schema_version`, `migrate`, `MIGRATIONS`, `create_blank_database`), `udl/__init__.py`, `udl/demo.py`, `make_clean_db.py`, `.gitignore`
- Create: `tests/fixtures/legacy_v0.sqlite`, `tests/test_migrations.py`

- [ ] **Step 1: Capture a pre-change database as a fixture**

The repo's working `udl_marks_db.sqlite` was created by the old `init_db` (fictional demo students only).
```bash
mkdir -p tests/fixtures
cp udl_marks_db.sqlite tests/fixtures/legacy_v0.sqlite
python -c "import sqlite3;c=sqlite3.connect('tests/fixtures/legacy_v0.sqlite');print(c.execute('select count(*) from attempts').fetchone(), c.execute(\"select * from _meta\").fetchall())"
```
Expected: a non-zero attempt count, and `_meta` with only `('seeded', 'true')` (no `schema_version`).

Add to the end of `.gitignore`:
```
!tests/fixtures/*.sqlite
```

- [ ] **Step 2: Write the failing tests**

`tests/test_migrations.py`:
```python
import shutil
import sqlite3
from pathlib import Path

from helpers import q
from udl.db import MIGRATIONS, create_blank_database, migrate

LEGACY = Path(__file__).parent / 'fixtures' / 'legacy_v0.sqlite'
LATEST = len(MIGRATIONS)
COUNTED = ('students', 'classes', 'student_classes', 'outcomes', 'attempts',
           'attempt_outcomes', 'scoring_detail')


def counts(path):
    return {t: q(path, f"SELECT COUNT(*) FROM {t}")[0][0] for t in COUNTED}


def version(path):
    return int(q(path, "SELECT value FROM _meta WHERE key = 'schema_version'")[0][0])


def test_fresh_database_gets_full_schema(tmp_path):
    path = str(tmp_path / 'fresh.sqlite')
    assert migrate(path) == LATEST
    assert version(path) == LATEST
    assert q(path, "SELECT stage_name FROM stages ORDER BY stage_id") == \
        [('Stage 3',), ('Stage 4',), ('Stage 5',)]
    assert 'class_code' in [r[1] for r in q(path, "PRAGMA table_info(classes)")]


def test_migrate_is_idempotent_and_skips_backup_when_nothing_pending(tmp_path):
    path = str(tmp_path / 'fresh.sqlite')
    migrate(path)
    calls = []
    assert migrate(path, before_migrate=lambda a, b: calls.append((a, b))) == LATEST
    assert calls == []


def test_fresh_database_does_not_request_backup(tmp_path):
    calls = []
    migrate(str(tmp_path / 'fresh.sqlite'), before_migrate=lambda a, b: calls.append((a, b)))
    assert calls == []


def test_legacy_database_upgrades_without_losing_anything(tmp_path):
    path = str(tmp_path / 'legacy.sqlite')
    shutil.copy(LEGACY, path)
    before = counts(path)
    calls = []
    migrate(path, before_migrate=lambda a, b: calls.append((a, b)))
    assert calls == [(0, LATEST)]
    assert counts(path) == before
    assert version(path) == LATEST
    assert 'class_id' in [r[1] for r in q(path, "PRAGMA table_info(attempts)")]


def test_dedupe_migration_merges_duplicate_classes(tmp_path):
    path = str(tmp_path / 'dupes.sqlite')
    migrate(path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO subjects (subject_name) VALUES ('Science')")
    conn.execute("INSERT INTO students (student_id, first_name, last_name, year_group) "
                 "VALUES (1, 'A', 'B', 'Year 7')")
    stage = conn.execute("SELECT stage_id FROM stages WHERE stage_name = 'Stage 4'").fetchone()[0]
    for _ in range(2):
        conn.execute("INSERT INTO classes (subject_id, year_group, stage_id) VALUES (1, 'Year 7', ?)", (stage,))
    conn.execute("INSERT INTO student_classes (student_id, class_id) VALUES (1, 2)")
    conn.execute("INSERT INTO attempts (student_id, class_id, attempt_date, assessment_title) "
                 "VALUES (1, 2, '2026-01-01', 'T')")
    conn.execute("UPDATE _meta SET value = '1' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    migrate(path)
    assert q(path, "SELECT class_id FROM classes") == [(1,)]
    assert q(path, "SELECT class_id FROM student_classes") == [(1,)]
    assert q(path, "SELECT class_id FROM attempts") == [(1,)]


def test_create_blank_database_marks_it_seeded(tmp_path):
    path = str(tmp_path / 'blank.sqlite')
    create_blank_database(path)
    assert version(path) == LATEST
    assert q(path, "SELECT value FROM _meta WHERE key = 'seeded'") == [('true',)]
    assert q(path, "SELECT COUNT(*) FROM students") == [(0,)]
```

- [ ] **Step 3: Run to confirm failure**

Run: `python -m pytest tests/test_migrations.py -v`
Expected: collection ERROR, `ImportError: cannot import name 'MIGRATIONS'`.

- [ ] **Step 4: Implement migrations**

In `udl/db.py`, delete the whole `init_db` function and add in its place:
```python
# ── Migrations ───────────────────────────────────────────────────────────────
# Each migration runs exactly once, in its own transaction, and bumps
# _meta.schema_version. Never edit a released migration; add a new one.

def _m001_baseline(conn):
    """Schema as it stood before versioning. Safe on fresh and pre-versioning databases."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stages (
            stage_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_name TEXT UNIQUE NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stage_years (
            stage_id   INTEGER NOT NULL,
            year_group TEXT    NOT NULL,
            PRIMARY KEY (stage_id, year_group),
            FOREIGN KEY (stage_id) REFERENCES stages(stage_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id      INTEGER PRIMARY KEY,
            first_name      TEXT NOT NULL,
            last_name       TEXT NOT NULL,
            year_group      TEXT,
            enrollment_date DATE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            subject_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_name TEXT UNIQUE NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS classes (
            class_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            year_group TEXT    NOT NULL,
            stage_id   INTEGER NOT NULL,
            FOREIGN KEY (subject_id) REFERENCES subjects(subject_id),
            FOREIGN KEY (stage_id)   REFERENCES stages(stage_id)
        )
    """)
    conn.execute("""
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
    conn.execute("""
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attempt_outcomes (
            attempt_outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id         INTEGER NOT NULL,
            outcome_id         INTEGER NOT NULL,
            FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id),
            FOREIGN KEY (outcome_id) REFERENCES outcomes(outcome_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scoring_detail (
            scoring_detail_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_outcome_id INTEGER NOT NULL,
            score              INTEGER NOT NULL,
            FOREIGN KEY (attempt_outcome_id) REFERENCES attempt_outcomes(attempt_outcome_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS student_classes (
            student_id INTEGER NOT NULL,
            class_id   INTEGER NOT NULL,
            PRIMARY KEY (student_id, class_id),
            FOREIGN KEY (student_id) REFERENCES students(student_id),
            FOREIGN KEY (class_id)   REFERENCES classes(class_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL
        )
    """)

    # Columns added over time. Each fails harmlessly if already present.
    # (The old list also tried to DROP attempts.class_id; that has been removed on purpose.)
    for sql in (
        "ALTER TABLE students ADD COLUMN year_group TEXT",
        "ALTER TABLE classes  RENAME COLUMN grade_level TO year_group",
        "ALTER TABLE classes  ADD COLUMN stage_id   INTEGER REFERENCES stages(stage_id)",
        "ALTER TABLE classes  ADD COLUMN class_code TEXT",
        "ALTER TABLE outcomes ADD COLUMN subject_id INTEGER REFERENCES subjects(subject_id)",
        "ALTER TABLE outcomes ADD COLUMN stage_id   INTEGER REFERENCES stages(stage_id)",
    ):
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass

    # Stage/year structure is curriculum config, not sample data.
    for stage_name, years in (('Stage 3', ('Year 5', 'Year 6')),
                              ('Stage 4', ('Year 7', 'Year 8')),
                              ('Stage 5', ('Year 9', 'Year 10'))):
        conn.execute("INSERT OR IGNORE INTO stages (stage_name) VALUES (?)", (stage_name,))
        stage_id = conn.execute("SELECT stage_id FROM stages WHERE stage_name = ?",
                                (stage_name,)).fetchone()[0]
        for year in years:
            conn.execute("INSERT OR IGNORE INTO stage_years (stage_id, year_group) VALUES (?, ?)",
                         (stage_id, year))

    # Databases that predate explicit rosters: derive enrolments from year group once.
    if conn.execute("SELECT COUNT(*) FROM student_classes").fetchone()[0] == 0:
        conn.execute("""
            INSERT OR IGNORE INTO student_classes (student_id, class_id)
            SELECT s.student_id, c.class_id
            FROM students s
            JOIN classes c ON s.year_group = c.year_group
            WHERE s.year_group IS NOT NULL
        """)


def _m002_dedupe_classes(conn):
    """Merge duplicate classes (same subject, year and code) created by old repeated seeding."""
    canonical = "SELECT MIN(class_id) FROM classes GROUP BY subject_id, year_group, COALESCE(class_code, '')"
    conn.execute(f"""
        INSERT OR IGNORE INTO student_classes (student_id, class_id)
        SELECT sc.student_id,
               (SELECT MIN(c2.class_id) FROM classes c2
                WHERE c2.subject_id = c1.subject_id
                  AND c2.year_group  = c1.year_group
                  AND COALESCE(c2.class_code, '') = COALESCE(c1.class_code, ''))
        FROM student_classes sc
        JOIN classes c1 ON c1.class_id = sc.class_id
        WHERE sc.class_id NOT IN ({canonical})
    """)
    conn.execute(f"DELETE FROM student_classes WHERE class_id NOT IN ({canonical})")
    conn.execute(f"""
        UPDATE attempts
        SET class_id = (
            SELECT MIN(c2.class_id) FROM classes c2
            WHERE c2.subject_id = (SELECT subject_id FROM classes WHERE class_id = attempts.class_id)
              AND c2.year_group  = (SELECT year_group  FROM classes WHERE class_id = attempts.class_id)
              AND COALESCE(c2.class_code, '') =
                  COALESCE((SELECT class_code FROM classes WHERE class_id = attempts.class_id), '')
        )
        WHERE class_id IS NOT NULL AND class_id NOT IN ({canonical})
    """)
    conn.execute(f"DELETE FROM classes WHERE class_id NOT IN ({canonical})")


MIGRATIONS = [_m001_baseline, _m002_dedupe_classes]


def schema_version(conn):
    row = conn.execute("SELECT value FROM _meta WHERE key = 'schema_version'").fetchone()
    return int(row[0]) if row else 0


def migrate(db_path, before_migrate=None):
    """Bring the database up to the latest schema, creating it if needed. Returns the version.

    before_migrate(from_version, to_version) is called once before anything changes, but only
    when an existing database with data is about to be upgraded (used for pre-upgrade backups).
    Safe to run from two computers at once: each step re-checks the version under the write lock.
    """
    conn = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        current, target = schema_version(conn), len(MIGRATIONS)
        if current >= target:
            return current
        has_data = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'students'").fetchone()
        if before_migrate and has_data:
            before_migrate(current, target)
        conn.execute("PRAGMA foreign_keys = OFF")  # migrations may reshape linked tables
        for version in range(current + 1, target + 1):
            conn.execute("BEGIN IMMEDIATE")
            try:
                if schema_version(conn) >= version:  # another computer got here first
                    conn.execute("COMMIT")
                    continue
                MIGRATIONS[version - 1](conn)
                conn.execute(
                    "INSERT INTO _meta (key, value) VALUES ('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(version),))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return target
    finally:
        conn.close()


def create_blank_database(db_path):
    """A new empty database with the curriculum structure and no demo data."""
    migrate(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT OR IGNORE INTO _meta (key, value) VALUES ('seeded', 'true')")
    conn.commit()
    conn.close()
```

- [ ] **Step 5: Switch callers from `init_db` to the new functions**

- `udl/__init__.py`: `db.init_db(app.config['DATABASE'])` → `db.migrate(app.config['DATABASE'])`
- `udl/demo.py`: the import line becomes `from .db import connect, migrate`, and in the `__main__` block `init_db(path)` → `migrate(path)`
- `make_clean_db.py`: replace everything from `db.init_db(db_path)` through `conn.close()` with `db.create_blank_database(db_path)`, and remove the now-unused `import sqlite3`

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest -q && python -m pyflakes udl make_clean_db.py && grep -rn "init_db" udl app.py make_clean_db.py tests || echo "no init_db left"`
Expected: `58 passed`, no pyflakes output, `no init_db left`.

- [ ] **Step 7: Commit**

```bash
git add -f tests/fixtures/legacy_v0.sqlite
git add .gitignore udl make_clean_db.py tests/test_migrations.py
git commit -m "feat: versioned migrations run once each; remove dangerous DROP COLUMN attempt"
```

---

### Task 10: `live_attempts` view, used by every report

Stage 5 (a later plan) adds soft deletes. For deleted marks to vanish everywhere, every report must read through one view. This task creates the view (for now it simply shows all attempts) and moves every report query onto it, with the snapshots proving nothing changed.

**Files:**
- Modify: `udl/db.py` (migration 3), `udl/analytics.py`, `udl/admin.py`
- Test: `tests/test_migrations.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_migrations.py`:
```python


ROOT = Path(__file__).resolve().parent.parent


def test_live_attempts_view_exists_and_returns_attempts(app, db_path):
    assert q(db_path, "SELECT COUNT(*) FROM live_attempts") == [(6,)]


def test_report_modules_only_read_live_attempts():
    import re
    for module in ('analytics.py', 'admin.py'):
        source = (ROOT / 'udl' / module).read_text(encoding='utf-8')
        raw = re.findall(r'\b(?:FROM|JOIN)\s+attempts\b', source, flags=re.IGNORECASE)
        assert raw == [], f'{module} reads the raw attempts table: {raw}'
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_migrations.py -v`
Expected: both new tests FAIL (no such table `live_attempts`; raw reads found).

- [ ] **Step 3: Add migration 3**

In `udl/db.py`, above `MIGRATIONS`, add:
```python
def _m003_live_attempts_view(conn):
    """Every report reads attempts through this view, so hidden (soft-deleted) marks
    can be excluded in one place. Until soft delete exists it shows everything."""
    conn.execute("CREATE VIEW IF NOT EXISTS live_attempts AS SELECT * FROM attempts")
```
and change the list to:
```python
MIGRATIONS = [_m001_baseline, _m002_dedupe_classes, _m003_live_attempts_view]
```

- [ ] **Step 4: Point report queries at the view**

Run:
```bash
sed -i -E 's/\b(FROM|JOIN)( +)attempts\b/\1\2live_attempts/g' udl/analytics.py udl/admin.py
grep -nE "live_attempts" udl/analytics.py udl/admin.py | wc -l
```
Expected: 10 or more matching lines. `udl/entry.py` is deliberately left alone, since it only *writes* to `attempts`.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: `60 passed`. All 28 snapshots unchanged.

- [ ] **Step 6: Commit**

```bash
git add udl tests/test_migrations.py
git commit -m "feat: live_attempts view; all reports read through it"
```

---

### Task 11: Refuse unsafe database locations

**Files:**
- Create: `udl/location.py`, `tests/test_location.py`, `tests/test_app_states.py`
- Modify: `udl/__init__.py`, `docs/superpowers/specs/2026-09-26-multi-teacher-foundations-design.md` (section 2 table: the path check lives in `udl/location.py`)

- [ ] **Step 1: Write the failing unit tests**

`tests/test_location.py`:
```python
import os

from udl.location import resolve_unc, unsafe_location_reason


def no_mapping(path):
    return os.path.abspath(path)


def test_ordinary_path_is_safe(tmp_path):
    assert unsafe_location_reason(str(tmp_path / 'db.sqlite'), env={}, resolver=no_mapping) is None


def test_path_inside_onedrive_is_refused(tmp_path):
    od = tmp_path / 'OneDrive - School'
    reason = unsafe_location_reason(str(od / 'UDL' / 'db.sqlite'),
                                    env={'OneDriveCommercial': str(od)}, resolver=no_mapping)
    assert reason and 'OneDrive' in reason


def test_sibling_folder_with_similar_name_is_not_onedrive(tmp_path):
    env = {'OneDrive': str(tmp_path / 'OneDrive')}
    assert unsafe_location_reason(str(tmp_path / 'OneDriveBackup' / 'db.sqlite'),
                                  env=env, resolver=no_mapping) is None


def test_webdav_sharepoint_mapping_is_refused():
    def to_webdav(path):
        return r'\\school.sharepoint.com@SSL\DavWWWRoot\sites\science\db.sqlite'
    reason = unsafe_location_reason(r'W:\db.sqlite', env={}, resolver=to_webdav)
    assert reason and 'SharePoint' in reason


def test_file_server_folder_named_sharepoint_is_allowed():
    def to_file_server(path):
        return r'\\fs01\SharePoint\Science\db.sqlite'
    assert unsafe_location_reason(r'W:\Science\db.sqlite', env={}, resolver=to_file_server) is None


def test_resolve_unc_leaves_local_paths_alone(tmp_path):
    path = str(tmp_path / 'db.sqlite')
    assert resolve_unc(path) == os.path.abspath(path)
```

`tests/test_app_states.py`:
```python
import os

from udl import create_app


def test_app_refuses_database_inside_onedrive(tmp_path, monkeypatch):
    od = tmp_path / 'OneDrive - School'
    od.mkdir()
    monkeypatch.setenv('OneDriveCommercial', str(od))
    db_file = od / 'udl.sqlite'
    client = create_app(str(db_file)).test_client()
    resp = client.get('/')
    assert resp.status_code == 503
    assert 'OneDrive' in resp.get_data(as_text=True)
    assert client.get('/settings').status_code == 503
    assert not os.path.exists(db_file)
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_location.py tests/test_app_states.py -v`
Expected: ImportError for `udl.location`.

- [ ] **Step 3: Implement the check**

`udl/location.py`:
```python
"""Refuse to open the database from places where SQLite files get corrupted.

OneDrive-synced folders keep a copy per computer and merge whole files; SharePoint mapped as a
WebDAV drive has no proper file locking. A normal Windows file share (\\\\server\\share) is fine.
"""
import os
import re
import sys

WEBDAV_MARKERS = ('@ssl', 'davwwwroot', '.sharepoint.com')


def resolve_unc(path):
    """Return the network target behind a mapped drive letter (W:\\x -> \\\\server\\share\\x).

    Local drives, non-Windows systems and failed lookups return the absolute path unchanged.
    """
    path = os.path.abspath(path)
    drive, rest = os.path.splitdrive(path)
    if sys.platform != 'win32' or not re.fullmatch(r'[A-Za-z]:', drive):
        return path
    import ctypes
    from ctypes import wintypes
    buf = ctypes.create_unicode_buffer(1024)
    size = wintypes.DWORD(len(buf))
    if ctypes.windll.mpr.WNetGetConnectionW(drive, buf, ctypes.byref(size)) != 0:
        return path  # not a mapped network drive
    return buf.value.rstrip('\\') + rest


def unsafe_location_reason(db_path, env=None, resolver=resolve_unc):
    """Return a plain-English explanation if db_path is unsafe, otherwise None."""
    env = os.environ if env is None else env
    local = os.path.normcase(os.path.abspath(db_path))
    for key, value in env.items():
        if key.upper().startswith('ONEDRIVE') and value:
            root = os.path.normcase(os.path.abspath(value)).rstrip('\\/')
            if local == root or local.startswith(root + os.sep):
                return (f'The database is inside a OneDrive-synced folder ({value}). OneDrive keeps a '
                        'separate copy on each computer and merges them, which corrupts databases and '
                        'loses marks. Move the whole UDL Marks DB folder to the school network drive '
                        'and start it from there.')
    target = resolver(db_path)
    if any(marker in target.lower() for marker in WEBDAV_MARKERS):
        return (f'The database is on a SharePoint web location ({target}). That kind of drive '
                'cannot safely hold a database. Put the UDL Marks DB folder on a normal school '
                'network share instead (ask IT if unsure).')
    return None
```

- [ ] **Step 4: Gate the app on it**

Replace `udl/__init__.py` `create_app` with the version below. The blueprints and error handlers stay the same; the database-state gate is new.
```python
def create_app(db_path=None):
    app = Flask(__name__, template_folder=str(ROOT / 'templates'))
    path = str(db_path or os.environ.get('UDL_DB_PATH') or DEFAULT_DB_PATH)
    app.config['DATABASE'] = path
    app.config['DB_BUSY_TIMEOUT_MS'] = db.BUSY_TIMEOUT_MS

    from .admin import bp as admin_bp
    from .analytics import bp as analytics_bp
    from .entry import bp as entry_bp
    app.register_blueprint(analytics_bp)
    app.register_blueprint(entry_bp)
    app.register_blueprint(admin_bp)

    problem = unsafe_location_reason(path)
    if problem:
        print('\n*** UDL Marks DB will not open this database ***\n' + problem + '\n')
        app.config['DB_STATE'], app.config['DB_PROBLEM'] = 'unsafe', problem
    else:
        db.migrate(path)
        app.config['DB_STATE'] = 'ready'

    @app.before_request
    def gate_on_database_state():
        if app.config['DB_STATE'] == 'unsafe':
            return render_template('error.html', title='Database location is not safe',
                                   message=app.config['DB_PROBLEM']), 503
        return None

    @app.errorhandler(sqlite3.OperationalError)
    def database_unavailable(err):
        app.logger.error('Database error: %s', err)
        return render_template(
            'error.html', title='Changes not saved',
            message='The database is busy or unreachable, so your changes were not saved. '
                    'Wait a few seconds and try again. If this keeps happening, check that '
                    'this computer can open the shared drive.'), 503

    @app.errorhandler(500)
    def server_error(err):
        return render_template(
            'error.html', title='Something went wrong',
            message='The app hit an unexpected problem and nothing was changed by this request. '
                    'Try again; if it keeps happening, note what you were doing and tell the '
                    'person who looks after UDL Marks DB.'), 500

    return app
```
Add `from .location import unsafe_location_reason` below `from . import db`.

In the spec's section 2 table, change the `udl/db.py` row to read "Connections, pragmas, schema and migrations, `live_*` views, shared query helpers", and add a row: `udl/location.py` | "Startup path safety check (OneDrive/WebDAV refusal, drive-letter resolution)".

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q && python -m pyflakes udl`
Expected: `67 passed`, no pyflakes output.

- [ ] **Step 6: Commit**

```bash
git add udl tests/test_location.py tests/test_app_states.py docs/superpowers/specs/2026-09-26-multi-teacher-foundations-design.md
git commit -m "feat: refuse to open the database from OneDrive or SharePoint-WebDAV locations"
```

---

### Task 12: Ask before creating a missing database

**Files:**
- Create: `templates/create_database.html`
- Modify: `udl/__init__.py`, `tests/conftest.py`
- Test: `tests/test_app_states.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app_states.py`:
```python


def test_missing_database_asks_before_creating(tmp_path):
    db_file = tmp_path / 'udl.sqlite'
    client = create_app(str(db_file)).test_client()
    resp = client.get('/')
    assert resp.status_code == 503
    text = resp.get_data(as_text=True)
    assert 'No database found' in text and str(db_file) in text
    assert not os.path.exists(db_file)

    resp = client.post('/setup/create-database')
    assert resp.status_code == 302
    assert os.path.exists(db_file)
    assert client.get('/').status_code == 200


def test_create_if_missing_skips_the_question(tmp_path):
    db_file = tmp_path / 'udl.sqlite'
    client = create_app(str(db_file), create_if_missing=True).test_client()
    assert os.path.exists(db_file)
    assert client.get('/').status_code == 200


def test_create_endpoint_does_nothing_when_database_exists(client):
    assert client.post('/setup/create-database').status_code == 404
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_app_states.py -v`
Expected: the three new tests FAIL (the database is created silently; `create_if_missing` is an unexpected keyword).

- [ ] **Step 3: Create the confirmation page**

`templates/create_database.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>No database found — UDL Marks DB</title>
    <style>
        body { font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa;
               color: #2d3748; margin: 0; padding: 48px 16px; }
        .card { max-width: 640px; margin: 0 auto; background: #fff; border-radius: 10px;
                padding: 28px 32px; box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                border-top: 5px solid #d69e2e; }
        h1 { font-size: 1.4rem; margin: 0 0 12px; }
        p { line-height: 1.55; }
        code { background: #edf2f7; padding: 2px 6px; border-radius: 4px; word-break: break-all; }
        button { background: #2c5282; color: #fff; border: 0; border-radius: 6px;
                 padding: 10px 18px; font-size: 1rem; cursor: pointer; }
    </style>
</head>
<body>
    <div class="card">
        <h1>No database found</h1>
        <p>UDL Marks DB looked for its database here:</p>
        <p><code>{{ db_path }}</code></p>
        <p><strong>If you expected to see existing marks, don't create a new one.</strong>
           Close this window and check that the shared drive is connected and that you started
           the app from the right folder.</p>
        <p>If this is a brand-new installation, create an empty database:</p>
        <form method="post" action="/setup/create-database">
            <button type="submit">Create a new empty database here</button>
        </form>
    </div>
</body>
</html>
```

- [ ] **Step 4: Implement the missing state**

In `udl/__init__.py`:
- Add `redirect` and `request` to the Flask import: `from flask import Flask, abort, redirect, render_template, request`.
- Change the signature to `def create_app(db_path=None, create_if_missing=False):`.
- Replace the `else:` branch after the `problem` check with:
```python
    elif not os.path.exists(path) and not create_if_missing:
        app.config['DB_STATE'] = 'missing'
    else:
        db.migrate(path)
        app.config['DB_STATE'] = 'ready'
```
- Replace `gate_on_database_state` with:
```python
    @app.before_request
    def gate_on_database_state():
        state = app.config['DB_STATE']
        if state == 'unsafe':
            return render_template('error.html', title='Database location is not safe',
                                   message=app.config['DB_PROBLEM']), 503
        if state == 'missing':
            if request.method == 'POST' and request.path == '/setup/create-database':
                db.create_blank_database(path)
                app.config['DB_STATE'] = 'ready'
                return redirect('/')
            return render_template('create_database.html', db_path=path), 503
        if request.path == '/setup/create-database':
            abort(404)
        return None
```

- [ ] **Step 5: Let the test fixture create its database directly**

In `tests/conftest.py`, change `create_app(db_path)` to `create_app(db_path, create_if_missing=True)`.

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest -q && python -m pyflakes udl`
Expected: `70 passed`, no pyflakes output.

- [ ] **Step 7: Commit**

```bash
git add udl templates/create_database.html tests/conftest.py tests/test_app_states.py
git commit -m "feat: ask before creating a database instead of silently making an empty one"
```

---

### Task 13: Final verification against the real development database

**Files:**
- Modify: `PROJECT_PROGRESS.md`

- [ ] **Step 1: Full suite and lint**

Run: `python -m pytest -q && python -m pyflakes app.py udl make_clean_db.py`
Expected: `70 passed`, no pyflakes output.

- [ ] **Step 2: Back up the development database, then start the real app on it**

```bash
cp udl_marks_db.sqlite "udl_marks_db.pre-migration-$(date +%Y%m%d).sqlite"
UDL_DEBUG=1 python app.py
```
Run it in the background (Bash `run_in_background`), or in a terminal. Expected console output: Flask's `Running on http://127.0.0.1:5000`, with no traceback.

- [ ] **Step 3: Click through the key pages**

Open http://127.0.0.1:5000 in the browser pane and load: Home, History, Analytics, one class heatmap (Peak and Average), one student progress page, Settings → Students, Classes, Outcomes, and the Single / Bulk / Import entry pages. Each must render with the existing marks visible. Then check the upgrade:
```bash
python -c "import sqlite3;c=sqlite3.connect('udl_marks_db.sqlite');print(c.execute(\"select value from _meta where key='schema_version'\").fetchone())"
```
Expected: `('3',)`.

Stop the server afterwards.

- [ ] **Step 4: Record progress**

Add a new session section at the top of `PROJECT_PROGRESS.md` (below the title):
```markdown
## Session: 2026-09-26 — Foundations (plan 1 of the multi-teacher work)

- Removed the database and tool caches from git; Flask debug only via `run.bat`.
- Design spec: `docs/superpowers/specs/2026-09-26-multi-teacher-foundations-design.md`.
- `app.py` split into the `udl/` package (analytics / entry / admin blueprints) with no behaviour change, proven by page-snapshot tests.
- Class codes now show on Home, History and Analytics.
- Network-drive-safe SQLite settings; friendly "not saved" page when the database is busy.
- Versioned migrations (each runs once), a `live_attempts` view used by all reports,
  refusal to run from OneDrive/SharePoint-WebDAV folders, and a confirmation before creating a missing database.
- Demo data is no longer loaded automatically: `python -m udl.demo`.

Next: plan 2 — backups (daily 14 / monthly 12 / manual), then logins and roles, then intentional editing.
```

- [ ] **Step 5: Commit**

```bash
git add PROJECT_PROGRESS.md
git commit -m "docs: record foundations progress"
```
