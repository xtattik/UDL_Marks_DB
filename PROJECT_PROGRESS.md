Project Progress — UDL_Marks_DB
================================

Date: 2026-05-22

Summary of recent work
- Implemented a searchable, client-side Outcome selector with suggestions and token-style multi-select.
- Added backend API endpoint `/api/outcomes?q=...` to return matching outcomes as JSON.
- Updated `marks_entry` POST handler to accept multiple `outcome_ids` and store scoring for each selected outcome.

Files changed
- `app.py`: add `/api/outcomes` endpoint and support multi-outcome submission; adjusted attempt insert logic.
- `templates/marks_entry.html`: replaced static outcome `<select>` with searchable multi-select UI and supporting JS/CSS.

How to run locally
1. Create and activate a Python virtualenv.
2. Install dependencies from `requirements.txt`.
3. Run the app and open `http://localhost:5000/marks/new`.

Quick commands (PowerShell):
```powershell
python -m venv venv
venv\Scripts\Activate
pip install -r requirements.txt
python app.py
```

Notes & next steps
- Add keyboard navigation (arrow/enter) to suggestion list.
- Add server-side validation and audit logging for entries.
- Implement authentication later (disabled for local testing currently).

Commit: "Add searchable Outcome selector, outcomes API, and project progress doc"
