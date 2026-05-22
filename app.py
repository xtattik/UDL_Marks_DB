from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
import os

DATABASE = 'udl_marks_db.sqlite'
app = Flask(__name__)

# --- Database Functions ---

def get_db_connection():
    """Establishes and returns a database connection."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the SQLite database and creates the core tables."""
    print("Database initialization skipped for Flask run. Assuming tables exist.")
    # In a real deployment, this function would run once to create tables.
    pass

def seed_db():
    """Populates the database with initial test data."""
    print("Database seeding skipped for Flask run. Assuming data exists.")
    # In a real deployment, this function would run once to populate data.
    pass

# --- Routes ---

@app.route('/')
def index():
    """Landing page/Dashboard."""
    return "Welcome to the UDL Marks Database System! Ready to build the marks entry form."

@app.route('/marks/new', methods=['GET', 'POST'])
def marks_entry():
    """
    Handles the marks entry form.
    GET: Displays the form.
    POST: Processes the submitted marks and saves them to the database.
    """
    if request.method == 'POST':
        # 1. Get data from form
        try:
            # Note: In a real application, these IDs would come from complex session/auth logic.
            student_id = request.form.get('student_id')
            class_id = request.form.get('class_id')
            assessment_title = request.form.get('assessment_title')
            # Support multiple selected outcomes (outcome_ids[]) or a single outcome_id for backwards compatibility
            outcome_ids = request.form.getlist('outcome_ids')
            if not outcome_ids:
                single = request.form.get('outcome_id')
                if single:
                    outcome_ids = [single]
            
            # Scores for sections 1 through 6
            scores = {
                'section1': int(request.form.get('s1', 0)),
                'section2': int(request.form.get('s2', 0)),
                'section3': int(request.form.get('s3', 0)),
                'section4': int(request.form.get('s4', 0)),
                'section5': int(request.form.get('s5', 0)),
                'section6': int(request.form.get('s6', 0)),
            }

            conn = get_db_connection()
            cursor = conn.cursor()

            # 2. Create a new Attempt record (single attempt for this submission)
            cursor.execute("""
                INSERT INTO attempts (class_id, student_id, assessment_title, assessment_description, attempt_date)
                VALUES (?, ?, ?, ?, date('now'))
            """, (class_id, student_id, assessment_title, "Marks Entry"))
            attempt_id = cursor.lastrowid

            # 3. For each selected outcome, link and store scoring details
            for oid in outcome_ids:
                cursor.execute("""
                    INSERT INTO attempt_outcomes (attempt_id, outcome_id)
                    VALUES (?, ?)
                """, (attempt_id, oid))

                cursor.execute("""
                    INSERT INTO scoring_detail (attempt_id, outcome_id, section1, section2, section3, section4, section5, section6)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (attempt_id, oid, scores['section1'], scores['section2'], scores['section3'], scores['section4'], scores['section5'], scores['section6']))

            conn.commit()
            return redirect(url_for('index'))

        except Exception as e:
            print(f"Error during marks entry: {e}")
            return f"Error saving marks: {e}", 500
        finally:
            if 'conn' in locals() and conn:
                conn.close()

    # GET request: Fetch necessary data to populate the form
    conn = get_db_connection()
    
    # Fetch all students, outcomes, and classes for dropdowns
    students = conn.execute("SELECT id, first_name, last_name FROM students").fetchall()
    outcomes = conn.execute("SELECT id, outcome_code, description FROM outcomes").fetchall()
    classes = conn.execute("SELECT id, class_name FROM classes").fetchall()
    
    conn.close()

    # We need a template file for this to work, which I will create next.
    return render_template('marks_entry.html', students=students, outcomes=outcomes, classes=classes)


@app.route('/api/outcomes')
def api_outcomes():
    """Simple outcomes search API. Query with `?q=term` to filter by code or description."""
    q = request.args.get('q', '').strip()
    conn = get_db_connection()
    if q:
        qparam = f"%{q}%"
        rows = conn.execute("SELECT id, outcome_code, description FROM outcomes WHERE outcome_code LIKE ? OR description LIKE ? LIMIT 50", (qparam, qparam)).fetchall()
    else:
        rows = conn.execute("SELECT id, outcome_code, description FROM outcomes LIMIT 200").fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append({'id': r['id'], 'code': r['outcome_code'], 'description': r['description']})
    return jsonify(results)

if __name__ == '__main__':
    # Run the application
    app.run(debug=True)