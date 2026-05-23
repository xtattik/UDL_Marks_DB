import sqlite3

conn = sqlite3.connect('udl_marks_db.sqlite')
cur = conn.cursor()

print('Tables:', [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])
print('\nSubjects:')
for row in cur.execute('SELECT * FROM subjects'):
    print(f'  {row}')
print('\nOutcomes count:', cur.execute('SELECT COUNT(*) FROM outcomes').fetchone()[0])
print('Students count:', cur.execute('SELECT COUNT(*) FROM students').fetchone()[0])
print('Assessments count:', cur.execute('SELECT COUNT(*) FROM assessments').fetchone()[0])
print('Scoring details count:', cur.execute('SELECT COUNT(*) FROM scoring_details').fetchone()[0])

conn.close()
