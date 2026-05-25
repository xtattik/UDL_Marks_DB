"""
Bulk assessment importer — reads a structured CSV and returns a list of
dicts ready to insert into the database.

CSV format (see test_data/assessment_import_template.csv):
    Row 1:  AssessmentName, <name>
    Row 2:  AssessmentDate, <YYYY-MM-DD>
    Row 3:  AssessmentDescription, <text>
    Row 4:  (blank)
    Row 5:  headers — StudentID, StudentName, ClassCode,
                       Outcome1, Score1, Outcome2, Score2, ..., Comment
    Row 6+: one row per student

Scores must be integers 0–16.
Outcome codes must already exist in the outcomes table.
StudentID is matched against students.student_id (integer).

Adapted from the original Assessment Importer.py (MarkBook Project, ~2024).
Changes: Level (text descriptor) → Score (integer 0–16); removed pandas.
"""

import csv
from pathlib import Path


class ImportError(ValueError):
    pass


def parse_assessment_csv(file_path):
    """
    Parse an assessment CSV file.

    Returns:
        dict with keys:
            'assessment_name'        str
            'assessment_date'        str  (YYYY-MM-DD)
            'assessment_description' str
            'rows'                   list of dicts, each with:
                student_id, student_name, class_code,
                outcomes (list of {'outcome_code': str, 'score': int}),
                comment
    Raises:
        ImportError on structural problems.
        FileNotFoundError if the file doesn't exist.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        rows = list(reader)

    if len(rows) < 6:
        raise ImportError("File too short — expected metadata rows + header + at least one data row.")

    assessment_name        = _cell(rows, 0, 1, 'AssessmentName')
    assessment_date        = _cell(rows, 1, 1, 'AssessmentDate')
    assessment_description = _cell(rows, 2, 1, 'AssessmentDescription')

    # Row 3 should be blank; row 4 is the header
    header = [h.strip() for h in rows[4]]
    _expect_header(header)

    # Locate key columns by name so row length doesn't need to be exact
    comment_col = header.index('Comment')
    # Pad all data rows to at least header length
    data_rows = rows[5:]
    parsed = []

    for line_num, row in enumerate(data_rows, start=6):
        if not any(row):
            continue  # skip blank rows

        row = [c.strip() for c in row]
        if len(row) < len(header):
            row = row + [''] * (len(header) - len(row))

        student_id   = row[0]
        student_name = row[1]
        class_code   = row[2]
        comment      = row[comment_col]

        # Outcome/score pairs between ClassCode (col 3) and Comment column, stepping by 2
        outcomes = []
        for i in range(3, comment_col, 2):
            outcome_code = row[i].strip()
            score_raw    = row[i + 1].strip() if (i + 1) < len(row) else ''

            if not outcome_code and not score_raw:
                continue  # empty pair — end of outcomes for this student

            if not outcome_code or not score_raw:
                print(f"  Warning (line {line_num}): incomplete outcome/score pair at column {i + 1} — skipped.")
                continue

            try:
                score = int(score_raw)
            except ValueError:
                print(f"  Warning (line {line_num}): non-integer score '{score_raw}' for {outcome_code} — skipped.")
                continue

            if not (0 <= score <= 16):
                print(f"  Warning (line {line_num}): score {score} out of range (0–16) for {outcome_code} — clamped.")
                score = max(0, min(16, score))

            outcomes.append({'outcome_code': outcome_code, 'score': score})

        if not student_id:
            print(f"  Warning (line {line_num}): missing StudentID — row skipped.")
            continue

        parsed.append({
            'student_id':   student_id,
            'student_name': student_name,
            'class_code':   class_code,
            'outcomes':     outcomes,
            'comment':      comment,
        })

    return {
        'assessment_name':        assessment_name,
        'assessment_date':        assessment_date,
        'assessment_description': assessment_description,
        'rows':                   parsed,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _cell(rows, row_idx, col_idx, label):
    try:
        val = rows[row_idx][col_idx].strip()
        if not val:
            raise ImportError(f"'{label}' is empty in the metadata header.")
        return val
    except IndexError:
        raise ImportError(f"'{label}' row is missing or malformed.")


def _expect_header(header):
    required = {'StudentID', 'StudentName', 'ClassCode', 'Comment'}
    missing = required - set(header)
    if missing:
        raise ImportError(f"Header row is missing required columns: {missing}")


# ── CLI usage ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    import json

    target = sys.argv[1] if len(sys.argv) > 1 else 'test_data/assessment_import_template.csv'
    result = parse_assessment_csv(target)

    print(f"Assessment : {result['assessment_name']}")
    print(f"Date       : {result['assessment_date']}")
    print(f"Description: {result['assessment_description']}")
    print(f"Students   : {len(result['rows'])}")
    print()
    for r in result['rows']:
        print(f"  {r['student_id']:>6}  {r['student_name']:<20}  {r['class_code']:<10}  "
              f"{len(r['outcomes'])} outcome(s)  comment: {r['comment'] or '—'}")
        for o in r['outcomes']:
            print(f"           {o['outcome_code']:<12}  score: {o['score']}/16")
