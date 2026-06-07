Project Progress — UDL_Marks_DB
================================

---

## Session: 2026-06-07

### What was built

**Data entry**
- Single mark entry — cascading year group → class → student filters; student list loads dynamically from class roster via API
- Bulk entry — whole-class grid with outcomes as columns and students as rows; blank cells skipped, partial entry supported
- CSV mark import from the rubric marking tool (drag-and-drop); per-student result summary shown after import

**Student & class management (Settings section)**
- Browse, search, add, and edit individual students
- Bulk student import via CSV — upserts by Student ID, preserves all assessment history
- Manage classes with optional class codes (e.g. 9.1, 9T) to distinguish groups within the same year and subject
- Explicit `student_classes` enrolment table — replaces implicit year-group matching; class rosters managed via Settings → Classes → Roster
- Manage subjects (add Commerce, PDHPE, etc.)
- Manage outcomes — assign subject and stage, add new outcome codes; "Unassigned" filter highlights outcomes that won't appear in heatmaps

**Analytics**
- Class heatmap with **Peak / Average toggle** (defaults to Peak — rewards improvement over time)
- Cross-curricular support — unclassified attempts (no class assigned) route into the correct class heatmap via outcome subject + stage, provided the student is enrolled in that class
- Per-student progress view with subject and stage filters
- Analytics page filtering by stage, year group, and subject

**Infrastructure**
- `run.bat` — dev launcher; activates venv if present, installs deps, opens browser
- `build_release.bat` — builds a self-contained Windows ZIP (~20 MB) using Python 3.12 embeddable; no installation or admin rights required for end users
- `make_clean_db.py` — creates a blank production database (schema + Stage 3/4/5 structure only, no sample data)
- `_meta` table with `seeded` flag prevents demo data from loading on release installs
- Duplicate class dedup migration runs on startup
- `seed_db()` now guards on `_meta.seeded` flag; stage/year structure moved to `init_db()` (curriculum config, not sample data)
- `.gitignore` updated: `dist/`, `*-release.zip`, `.venv/`, `.frontend-slides/`

### How to run (development)

Double-click `run.bat`, or manually:

```powershell
python -m venv .venv
.venv\Scripts\Activate
pip install -r requirements.txt
python app.py
```

### How to build a release

```bat
build_release.bat
```

Requires internet access (downloads Python 3.12 embeddable + Flask). Produces `UDL-Marks-DB-release.zip`. End users unzip anywhere and double-click `Start UDL Marks DB.bat`.

### Commits this session
- `b8ba969` — feat: student management, bulk entry, class analytics, and import pipeline
- `0be708c` — feat: release packaging and clean-install support

---

## Session: 2026-05-22

### What was built
- Searchable, client-side outcome selector with suggestions and token-style multi-select
- Backend API endpoint `/api/outcomes?q=...` returning matching outcomes as JSON
- `marks_entry` POST handler updated to accept multiple `outcome_ids` and store scoring per outcome

### Files changed
- `app.py` — add `/api/outcomes` endpoint; multi-outcome submission; adjusted attempt insert logic
- `templates/marks_entry.html` — replaced static outcome `<select>` with searchable multi-select UI

### Commit
`"Add searchable Outcome selector, outcomes API, and project progress doc"`

---

## Suggested next steps

### 1. Academic year tracking
All attempts already store `attempt_date`, so year is derivable from existing data — no data loss. The addition of an `academic_year` filter surface (on Analytics, History, and the class heatmap) would let staff view 2026 and 2027 data separately without mixing cohorts. A dropdown on the analytics/history pages, and optionally a year field on the import form, is the main UI work required.

### 2. Outcome import from the rubric builder
Currently outcomes must be added one at a time in Settings → Outcomes, which doesn't scale when a new assessment references 10–15 new codes. Adding a CSV import for outcomes (columns: `outcome_code`, `outcome_name`, `is_theoretical`, `subject_name`, `stage_name`) would let teachers drop in a new rubric's outcome list before importing marks, and auto-assign subject + stage in one step.

### 3. Student report / export view
A per-student summary page suitable for printing or sharing — showing peak score per outcome, grouped by subject and stage, with trend indicators. Could also export to PDF or CSV for reporting to parents or faculty. The data is all present; this is purely a new view/template and optional export route.
