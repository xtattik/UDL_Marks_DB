from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
import os
from datetime import datetime

DATABASE = 'udl_marks_db.sqlite'
app = Flask(__name__)

# --- Database Functions ---

def get_db_connection():
    """Establishes and returns a database connection."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    """Initializes the SQLite database and creates the core tables."""
    conn = get_db_connection()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT,
            stage TEXT
        );

        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_name TEXT NOT NULL,
            subject_id INTEGER,
            FOREIGN KEY (subject_id) REFERENCES subjects(id)
        );

        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            outcome_code TEXT NOT NULL,
            description TEXT NOT NULL,
            subject_id INTEGER,
            class_id INTEGER,
            is_content BOOLEAN DEFAULT 0,
            focus_type TEXT,
            FOREIGN KEY (subject_id) REFERENCES subjects(id),
            FOREIGN KEY (class_id) REFERENCES classes(id)
        );

        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER,
            student_id INTEGER,
            assessment_title TEXT NOT NULL,
            assessment_description TEXT,
            attempt_date TEXT DEFAULT (date('now')),
            created_by TEXT DEFAULT 'teacher',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (class_id) REFERENCES classes(id),
            FOREIGN KEY (student_id) REFERENCES students(id)
        );

        CREATE TABLE IF NOT EXISTS attempt_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id INTEGER NOT NULL,
            outcome_id INTEGER NOT NULL,
            FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE,
            FOREIGN KEY (outcome_id) REFERENCES outcomes(id)
        );

        CREATE TABLE IF NOT EXISTS scoring_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id INTEGER NOT NULL,
            outcome_id INTEGER NOT NULL,
            section1 REAL DEFAULT 0,
            section2 REAL DEFAULT 0,
            section3 REAL DEFAULT 0,
            section4 REAL DEFAULT 0,
            section5 REAL DEFAULT 0,
            section6 REAL DEFAULT 0,
            FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE,
            FOREIGN KEY (outcome_id) REFERENCES outcomes(id)
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def seed_db():
    """Populates the database with initial test data."""
    conn = get_db_connection()

    # Check if data already exists
    if conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0] > 0:
        print("Database already seeded. Skipping.")
        conn.close()
        return

    # Subjects
    subjects = [
        ('Mathematics', 'MATH', 'Stage 4'),
        ('English', 'ENG', 'Stage 4'),
        ('Science', 'SCI', 'Stage 4'),
        ('Mathematics', 'MATH', 'Stage 5'),
        ('English', 'ENG', 'Stage 5'),
        ('Science', 'SCI', 'Stage 5'),
    ]
    conn.executemany("INSERT INTO subjects (name, code, stage) VALUES (?, ?, ?)", subjects)

    # Classes
    classes = [
        ('Stage 4 Science - A', 3),
        ('Stage 4 Science - B', 3),
        ('Stage 5 Science - A', 6),
        ('Stage 4 Math - A', 1),
        ('Stage 4 English - A', 2),
    ]
    conn.executemany("INSERT INTO classes (class_name, subject_id) VALUES (?, ?)", classes)

    # Outcomes - Sample NSW Stage 4 Science outcomes
    outcomes = [
        ('SC4-1MW', 'Describes and evaluates investigations in terms of the hypotheses, variables, ranges, increments, reliability and validity', 3, 1, 1, 'Theoretical'),
        ('SC4-2MW', 'Processes data and information to propose evidence-based explanations and arguments', 3, 1, 1, 'Applied'),
        ('SC4-3MW', 'Uses scientific understanding to describe living and non-living matter in terms of relevant models and theories', 3, 1, 1, 'Theoretical'),
        ('SC4-4MW', 'Evaluates claims and recommendations in relation to evidence obtained from a range of primary and/or secondary sources', 3, 1, 1, 'Applied'),
        ('SC4-5ES', 'Describes and explains how scientific knowledge, understanding and skills develop over time and through collaboration between scientists', 3, 1, 1, 'Theoretical'),
        ('SC4-6ES', 'Evaluates the role of technological systems on society and the environment and considers alternatives', 3, 1, 1, 'Applied'),
    ]
    conn.executemany("""INSERT INTO outcomes (outcome_code, description, subject_id, class_id, is_content, focus_type)
                        VALUES (?, ?, ?, ?, ?, ?)""", outcomes)

    # Sample students
    first_names = ['Alex', 'Blake', 'Casey', 'Dana', 'Ellis', 'Finley', 'Gray', 'Harper', 'Indigo', 'Jordan', 'Kai', 'Liam', 'Morgan', 'Noah', 'Olivia', 'Parker', 'Quinn', 'Riley', 'Sam', 'Taylor']
    last_names = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis', 'Rodriguez', 'Martinez', 'Hernandez', 'Lopez', 'Gonzalez', 'Wilson', 'Anderson', 'Thomas', 'Taylor', 'Moore', 'Jackson', 'Martin']
    for i, (first, last) in enumerate(zip(first_names, last_names)):
        conn.execute("INSERT INTO students (first_name, last_name) VALUES (?, ?)", (first, last))

    # Sample users
    conn.execute("INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)",
                 ('admin', 'placeholder', 'Admin Teacher'))

    conn.commit()
    conn.close()
    print("Database seeded successfully.")

# --- Routes ---

@app.route('/')
def index():
    """Landing page/Dashboard."""
    conn = get_db_connection()

    # Stats
    total_students = conn.execute("SELECT COUNT(*) as count FROM students").fetchone()['count']
    total_attempts = conn.execute("SELECT COUNT(*) as count FROM attempts").fetchone()['count']
    total_outcomes = conn.execute("SELECT COUNT(*) as count FROM outcomes").fetchone()['count']
    today_entries = conn.execute("SELECT COUNT(*) as count FROM attempts WHERE date(attempt_date) = date('now')").fetchone()['count']

    # Recent entries
    recent = conn.execute("""
        SELECT a.id, a.assessment_title, a.attempt_date, a.class_id, a.student_id,
               s.first_name, s.last_name, c.class_name
        FROM attempts a
        JOIN students s ON a.student_id = s.id
        JOIN classes c ON a.class_id = c.id
        ORDER BY a.created_at DESC LIMIT 5
    """).fetchall()

    conn.close()

    return render_template('index.html',
                           stats={'students': total_students, 'attempts': total_attempts,
                                  'outcomes': total_outcomes, 'today': today_entries},
                           recent=recent)

@app.route('/marks/new', methods=['GET', 'POST'])
def marks_entry():
    """Handles the marks entry form."""
       if request.method == 'POST':
        return handle_marks_submit(request)

    # GET request: Fetch data
    conn = get_db_connection()
    students = conn.execute("SELECT id, first_name, last_name FROM students ORDER BY last_name, first_name").fetchall()
    outcomes = conn.execute("""
        SELECT o.id, o.outcome_code, o.description, o.focus_type, s.name as subject_name
        FROM outcomes o
        LEFT JOIN subjects s ON o.subject_id = s.id
        ORDER BY o.outcome_code
    """).fetchall()
    classes = conn.execute("SELECT c.id, c.class_name, s.name as subject_name FROM classes c LEFT JOIN subjects s ON c.subject_id = s.id ORDER BY c.class_name").fetchall()
    conn.close()

   return render_template('marks_entry.html', students=students, outcomes=outcomes, classes=classes)

def handle_marks_submit(request):
    """Processes submitted marks and saves to database."""
    try:
        data = request.form
        student_id = data.get('student_id')
        class_id = data.get('class_id')
        assessment_title = data.get('assessment_title')
        assessment_description = data.get('assessment_description', '')

        if not student_id or not class_id or not assessment_title:
            return "Missing required fields: student, class, and assessment title are required.", 400

        # Get selected outcome IDs (comma-separated string from multi-select)
        outcome_ids_str = data.get('outcome_ids', '')
        outcome_ids = [int(x.strip()) for x in outcome_ids_str.split(',') if x.strip()]

        if not outcome_ids:
            return "Please select at least one outcome.", 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # Create Attempt record
        cursor.execute("""
            INSERT INTO attempts (class_id, student_id, assessment_title, assessment_description, attempt_date)
            VALUES (?, ?, ?, ?, date('now'))
        """, (class_id, student_id, assessment_title, assessment_description))
        attempt_id = cursor.lastrowid

        # Link each outcome and insert scoring detail
        for outcome_id in outcome_ids:
            # Link attempt to outcome
            cursor.execute("""
                INSERT INTO attempt_outcomes (attempt_id, outcome_id)
                VALUES (?, ?)
            """, (attempt_id, outcome_id))

            # Insert scoring detail - get all 6 sections
            scores = tuple(int(data.get(f's_{outcome_id}_{i}', 0)) for i in range(1, 7))
            cursor.execute("""
                INSERT INTO scoring_detail (attempt_id, outcome_id, section1, section2, section3, section4, section5, section6)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (attempt_id, outcome_id, *scores))

        conn.commit()
        conn.close()
        return redirect(url_for('index'))

    except Exception as e:
        print(f"Error during marks entry: {e}")
        if 'conn' in locals() and conn:
            conn.close()
        return f"Error saving marks: {e}", 500

@app.route('/recent')
def recent_entries():
    """Shows all submitted entries with pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db_connection()

    total = conn.execute("SELECT COUNT(*) as count FROM attempts").fetchone()['count']
    entries = conn.execute("""
        SELECT a.id, a.assessment_title, a.attempt_date, a.created_at,
               s.first_name, s.last_name, c.class_name,
               GROUP_CONCAT(o.outcome_code, ', ') as outcomes
        FROM attempts a
        JOIN students s ON a.student_id = s.id
        JOIN classes c ON a.class_id = c.id
        LEFT JOIN attempt_outcomes ao ON a.id = ao.attempt_id
        LEFT JOIN outcomes o ON ao.outcome_id = o.id
        GROUP BY a.id
        ORDER BY a.created_at DESC
        LIMIT ? OFFSET ?
    """, (per_page, offset)).fetchall()

    total_pages = (total + per_page - 1) // per_page
    conn.close()

    return render_template('recent.html', entries=entries, page=page, total_pages=total_pages, total=total)

# --- API Endpoints ---

@app.route('/api/outcomes')
def api_outcomes():
    """Returns outcomes as JSON for dynamic loading."""
    search = request.args.get('search', '')
    class_id = request.args.get('class_id', '', type=int)

    conn = get_db_connection()
    query = """
        SELECT o.id, o.outcome_code, o.description, o.focus_type, s.name as subject_name
        FROM outcomes o
        LEFT JOIN subjects s ON o.subject_id = s.id
    """
    params = []
    if search:
        query += " WHERE o.outcome_code LIKE ? OR o.description LIKE ?"
        params.extend([f'%{search}%', f'%{search}%'])
    if class_id:
        query += f"{'WHERE' if not search else 'AND'} o.class_id = ?"
        params.append(class_id)
    query += " ORDER BY o.outcome_code"

    outcomes = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify([{
        'id': o['id'],
        'code': o['outcome_code'],
        'description': o['description'],
        'focus_type': o['focus_type'],
        'subject': o['subject_name'] or 'General'
    } for o in outcomes])

@app.route('/api/students')
def api_students():
    """Returns students as JSON."""
    search = request.args.get('search', '')
    conn = get_db_connection()
    if search:
        students = conn.execute(
            "SELECT id, first_name, last_name FROM students WHERE first_name LIKE ? OR last_name LIKE ? OR first_name || ' ' || last_name LIKE ? ORDER BY last_name, first_name",
            (f'%{search}%', f'%{search}%', f'%{search}%')
        ).fetchall()
    else:
        students = conn.execute("SELECT id, first_name, last_name FROM students ORDER BY last_name, first_name").fetchall()
    conn.close()
    return jsonify([{ 'id': s['id'], 'name': f"{s['first_name']} {s['last_name']}" } for s in students])

@app.route('/api/classes')
def api_classes():
    """Returns classes as JSON."""
    conn = get_db_connection()
    classes = conn.execute(
        "SELECT c.id, c.class_name, s.name as subject_name FROM classes c LEFT JOIN subjects s ON c.subject_id = s.id ORDER BY c.class_name"
    ).fetchall()
    conn.close()
    return jsonify([{ 'id': c['id'], 'name': c['class_name'], 'subject': c['subject_name'] or '' } for c in classes])

# Initialize DB on module load (works for both `python app.py` and imports/tests)
with app.app_context():
    init_db()
    seed_db()


if __name__ == '__main__':
    app.run(debug=True)
