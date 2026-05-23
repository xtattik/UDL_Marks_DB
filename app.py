import sqlite3
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)
DATABASE = 'udl_marks_db.sqlite'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Students Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            enrollment_date DATE
        );
    """)

    # 2. Subjects Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            subject_id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_name TEXT UNIQUE NOT NULL
        );
    """)

    # 3. Classes Table (Links students to subjects/grades)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS classes (
            class_id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            grade_level TEXT NOT NULL,
            FOREIGN KEY (subject_id) REFERENCES subjects(subject_id)
        );
    """)

    # 4. Outcomes Table (NSW Stage 4 Outcomes)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS outcomes (
            outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
            outcome_code TEXT UNIQUE NOT NULL,
            outcome_name TEXT NOT NULL,
            is_theoretical BOOLEAN NOT NULL
        );
    """)

    # 5. Attempts Table (Assessment instances)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attempts (
            attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            class_id INTEGER NOT NULL,
            attempt_date DATE NOT NULL,
            assessment_title TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students(student_id),
            FOREIGN KEY (class_id) REFERENCES classes(class_id)
        );
    """)

    # 6. Attempt Outcomes Table (Links outcomes to a specific attempt)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attempt_outcomes (
            attempt_outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id INTEGER NOT NULL,
            outcome_id INTEGER NOT NULL,
            FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id),
            FOREIGN KEY (outcome_id) REFERENCES outcomes(outcome_id)
        );
    """)

    # 7. Scoring Detail Table (The actual marks)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scoring_detail (
            scoring_detail_id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_outcome_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            FOREIGN KEY (attempt_outcome_id) REFERENCES attempt_outcomes(attempt_outcome_id)
        );
    """)

    # 8. Users Table (For future authentication)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
        );
    """)

    conn.commit()
    conn.close()

def seed_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Seed Subjects
    subjects = [
        ('Mathematics',), ('Science',), ('English',)
    ]
    cursor.executemany("INSERT OR IGNORE INTO subjects (subject_name) VALUES (?)", subjects)

    # Seed Outcomes (Example NSW Stage 4)
    outcomes = [
        ('O1', 'Knowledge and understanding', 1),
        ('O2', 'Thinking and problem solving', 1),
        ('O3', 'Communication', 1),
        ('O4', 'Application', 1),
        ('O5', 'Critical evaluation', 1),
        ('O6', 'Creative expression', 1)
    ]
    cursor.executemany("INSERT OR IGNORE INTO outcomes (outcome_code, outcome_name, is_theoretical) VALUES (?, ?, ?)", outcomes)

    # Seed Students
    students = [
        ('Alice', 'Smith', '2023-01-15'),
        ('Bob', 'Johnson', '2023-02-20'),
        ('Charlie', 'Brown', '2023-03-10')
    ]
    cursor.executemany("INSERT OR IGNORE INTO students (first_name, last_name, enrollment_date) VALUES (?, ?, ?)", students)

    # Seed Classes (Linking subjects to classes)
    # Assuming Subject IDs 1=Math, 2=Science, 3=English
    classes = [
        (1, 'Stage 4',), (2, 'Stage 4',), (3, 'Stage 4',)
    ]
    cursor.executemany("INSERT OR IGNORE INTO classes (subject_id, grade_level) VALUES (?, ?)", classes)

    # Seed Default User
    cursor.execute("INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)", ('admin', 'hashed_password', 'teacher'))

    conn.commit()
    conn.close()

@app.route('/')
def index():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get key statistics
    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attempts")
    total_attempts = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM outcomes")
    total_outcomes = cursor.fetchone()[0]

    # Get 5 most recent attempts
    cursor.execute("""
        SELECT a.attempt_id, s.first_name, s.last_name, a.assessment_title, a.attempt_date
        FROM attempts a
        JOIN students s ON a.student_id = s.student_id
        ORDER BY a.attempt_date DESC
        LIMIT 5
    """)
    recent_attempts = cursor.fetchall()

    conn.close()
    return render_template('index.html', total_students=total_students, total_attempts=total_attempts, total_outcomes=total_outcomes, recent_attempts=recent_attempts)

@app.route('/marks/new', methods=['GET', 'POST'])
def marks_new():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch all students and outcomes for the form
    cursor.execute("SELECT student_id, first_name, last_name FROM students")
    students = cursor.fetchall()

    cursor.execute("SELECT outcome_id, outcome_code, outcome_name FROM outcomes")
    outcomes = cursor.fetchall()

    if request.method == 'POST':
        try:
            # --- Data Submission Logic ---
            student_id = request.form['student_id']
            assessment_title = request.form['assessment_title']
            attempt_date = request.form['attempt_date']
            class_id = request.form['class_id'] # Assuming class_id is passed from a hidden field or selection

            # 1. Create Attempt
            cursor.execute("""
                INSERT INTO attempts (student_id, class_id, attempt_date, assessment_title)
                VALUES (?, ?, ?, ?)
            """, (student_id, class_id, attempt_date, assessment_title))
            attempt_id = cursor.lastrowid

            # 2. Process Scores
            for outcome_id in request.form.getlist('outcome_ids'):
                score = int(request.form.get(f'score_{outcome_id}', 0))

                # 3. Link Outcome to Attempt
                cursor.execute("""
                    INSERT INTO attempt_outcomes (attempt_id, outcome_id)
                    VALUES (?, ?)
                """, (attempt_id, outcome_id))
                attempt_outcome_id = cursor.lastrowid

                # 4. Record Score
                cursor.execute("""
                    INSERT INTO scoring_detail (attempt_outcome_id, score)
                    VALUES (?, ?)
                """, (attempt_outcome_id, score))

            conn.commit()
            return redirect(url_for('index'))
        except Exception as e:
            print(f"Error during marks entry: {e}")
            return "Error submitting marks. Please try again.", 500

    conn.close()
    return render_template('marks_entry.html', students=students, outcomes=outcomes)

@app.route('/student/<int:student_id>')
def student_progress(student_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Get Student Details
    cursor.execute("SELECT * FROM students WHERE student_id = ?", (student_id,))
    student = cursor.fetchone()
    if not student:
        conn.close()
        return "Student not found", 404

    # 2. Get all Attempts for this student
    cursor.execute("""
        SELECT a.attempt_id, a.class_id, a.attempt_date, a.assessment_title
        FROM attempts a
        JOIN students s ON a.student_id = s.student_id
        WHERE s.student_id = ?
        ORDER BY a.attempt_date DESC
    """, (student_id,))
    attempts = cursor.fetchall()

    # 3. Get all Scoring Details for these attempts
    all_scoring_details = {}
    for attempt in attempts:
        attempt_id = attempt[0]
        # Fetch all outcomes/scores for this specific attempt
        cursor.execute("""
            SELECT sd.outcome_code, sd.score, o.outcome_name
            FROM scoring_detail sd
            JOIN attempt_outcomes ao ON sd.outcome_id = ao.outcome_id
            JOIN outcomes o ON ao.outcome_id = o.outcome_id
            WHERE ao.attempt_id = ?
        """, (attempt_id,))
        scores = cursor.fetchall()
        all_scoring_details[attempt_id] = scores

    conn.close()

    return render_template('student_progress.html', student=student, attempts=attempts, scores=all_scoring_details)

if __name__ == '__main__':
    init_db()
    seed_db()
    app.run(debug=True)