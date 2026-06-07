"""
Creates a clean distribution database.
Schema + stage/year structure only — no sample subjects, students, or outcomes.
The 'seeded' flag prevents sample data loading on first run.

Usage: python make_clean_db.py [output_path]
"""
import sys
import os

db_path = sys.argv[1] if len(sys.argv) > 1 else 'udl_marks_db.sqlite'

if os.path.exists(db_path):
    os.remove(db_path)

# Import app to reuse init_db (Flask is available in the embedded Python at this point)
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)
import app as _app

_app.DATABASE = db_path
_app.init_db()  # creates all tables + seeds stage/year structure

# Mark as seeded so sample data (students, demo classes, demo outcomes) never loads
import sqlite3
conn = sqlite3.connect(db_path)
conn.execute("INSERT OR IGNORE INTO _meta (key, value) VALUES ('seeded', 'true')")
conn.commit()
conn.close()

print(f"Clean database created: {db_path}")
