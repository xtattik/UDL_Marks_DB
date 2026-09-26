# Multi-Teacher Foundations — Design

**Date:** 2026-09-26
**Status:** Approved in brainstorming, awaiting written-spec review

## Goal

Make UDL Marks DB safe for several teachers to use from one shared database:
teachers sign in, marks record who entered them, corrections are deliberate
and logged, and the data is backed up in a way that can't silently discard
history.

## Context and constraints

- **Hosting, stage 1 (now):** the whole release folder lives on the school's
  mapped work\general drive. Each teacher runs the app locally on their own PC
  (127.0.0.1) against the shared SQLite file. There's no always-on server.
- **Hosting, stage 2 (later):** school IT hosts the same code under Waitress,
  and teachers visit a URL. This needs only a different launcher, with no
  code changes.
- The school has Microsoft SSO, but IT won't register the app yet. So we use
  app-managed accounts now, with an optional email field for SSO later.
- The repo is public and may be forked by a colleague, so clarity of structure
  matters.
- The release uses the Python 3.12 embeddable build plus Flask. Avoid new
  runtime dependencies (Werkzeug hashing and SQLite's backup API are
  already available).

## Out of scope (separate designs later)

Academic-year tracking and rollover, storing marking-tool comments, outcome
CSV import, the Theoretical/Applied label in exports, the broken `check_db.py`,
stale planning docs, and Microsoft SSO itself.

---

## 1. Runtime and deployment

- The release folder (program, `udl_marks_db.sqlite`, `backups/` and the
  launcher) sits in a faculty folder on the shared drive. Updating the app
  means replacing the program files in that one folder.
- Stage 1 launcher: `Start UDL Marks DB.bat` runs the app on the teacher's PC
  bound to 127.0.0.1:5000 and opens the browser. Flask debug is off unless
  `UDL_DEBUG=1` is set (already done in commit 3b1dab8; `run.bat` sets it for
  development).
- Stage 2: a `serve.py` entry point runs the same app under Waitress,
  bound to a configurable host/port. Waitress is added to requirements but
  used only by stage 2.
- The database path defaults to `udl_marks_db.sqlite` next to the program. It
  can be overridden with the `UDL_DB_PATH` environment variable (used by tests
  and stage 2).

## 2. Code layout

`app.py` becomes a thin entry point that calls `create_app()`. The code moves
into a `udl/` package, with one Flask blueprint per area:

| Module | Responsibility |
|---|---|
| `udl/__init__.py` | `create_app(db_path=None)`: config, secret key, blueprints, CSRF, login gate |
| `udl/db.py` | Connections, pragmas, path safety check, schema, migrations, `live_*` views, shared query helpers (e.g. `class_label_sql`) |
| `udl/auth.py` | Login/logout, first-admin setup, password change, `login_required` / `admin_required`, CSRF token helper |
| `udl/entry.py` | Single entry, bulk entry, CSV import, batches, edit/delete/restore of marks, duplicate check |
| `udl/analytics.py` | Dashboard, history, analytics, class heatmap, student progress, CSV export |
| `udl/admin.py` | Settings: students, classes, rosters, enrolment import, subjects, outcomes, teacher accounts, change log, deleted marks |
| `udl/backups.py` | Backup creation, rotation, verification, restore, and the Backups page routes |
| `udl/scoring.py` | Bands, `_score_band`, sparkline, `MAX_SCORE`, `DISCREPANCY_THRESHOLD`, merging in `utils/grade_scale.py` |

- All existing URLs and endpoint behaviour are unchanged. Templates call
  `url_for` with blueprint-prefixed endpoint names, updated in the same step.
- The class-display-name SQL, currently repeated about 8 times, becomes one
  helper. This fixes class codes missing on Home, History and Analytics.
- `utils/assessment_importer.py` is unused. Delete it unless the split shows
  it's needed.
- `build_release.bat` copies `udl/` and the new scripts. `make_clean_db.py`
  uses `create_app`/`db` instead of importing `app` internals.

## 3. Database layer and shared-drive safety

**Connection settings (every connection):** `journal_mode=DELETE` (never WAL,
which is unsafe on network filesystems), `busy_timeout=10000`,
`foreign_keys=ON`, `synchronous=FULL`.

**Short, atomic writes:** each request's writes happen in one transaction
opened as late as possible (`BEGIN IMMEDIATE` just before the first write),
then committed. Bulk entry and CSV import save all rows in one transaction:
all or nothing. If the lock can't be acquired within the timeout, the user
sees "The database is busy or unreachable — your entry was not saved. Please
try again," with the form data preserved where practical.

**Startup path check (before opening the DB):**
- Mapped drive letters are first resolved to their UNC target (Windows
  `WNetGetConnection` via `ctypes`), so a drive letter can't hide what it
  points to.
- Refuse to start if the resolved path is inside a OneDrive-synced folder
  (under any `OneDrive*` environment-variable path) or is a WebDAV path
  (`@SSL`, `DavWWWRoot`, `.sharepoint.com`). The console and a browser error
  page explain why and what to do.
- A plain file-server path whose folder names merely contain "SharePoint" is
  allowed (the school's drive may be named that way). Only the signals above
  cause a refusal.
- If the DB file doesn't exist, don't auto-create it silently. Show a page
  saying "No database found at <path>. Create a new empty database here?"
  that needs a click to confirm. Skip this for `make_clean_db.py` and tests,
  which create one explicitly.

**Migrations:** the existing try/except `ALTER` list is replaced by numbered
migrations tracked in `_meta.schema_version`. Before any pending migration
runs, a manual-type backup named "Before upgrade to schema vN" is made
automatically. The existing duplicate-class dedup becomes a one-time
migration rather than running on every startup.

**Live views:** `live_attempts` (attempts where `deleted_at IS NULL`) plus
joins built on it. Every report, analytics, history and export query reads
from live views only. Only edit/restore screens and admin audit pages touch
raw tables.

## 4. Backups

Stored in `backups/` next to the database:

| Folder | Trigger | Retention |
|---|---|---|
| `daily/` | First app start on a calendar day (any user) | The 14 most recent **distinct days**; at most one file per day |
| `monthly/` | First app start in a calendar month | The 12 most recent **distinct months**; at most one per month |
| `manual/` | Admin "Create backup" (name required), automatic pre-restore and pre-migration backups | **Never deleted automatically**; deleted one at a time by an admin with confirmation |

- **File naming:** `daily/2026-09-26.sqlite`, `monthly/2026-09.sqlite`,
  `manual/2026-09-26_1432_<slug-of-name>.sqlite`, with a sidecar `.json`
  holding the name, the creator, the time and the integrity result.
- Rotation deletes only from `daily/` and `monthly/`, only files matching the
  expected name pattern, and only once there are more than 14 or 12 distinct
  periods.
- Creation uses `sqlite3.Connection.backup()`, then runs `PRAGMA
  integrity_check` on the copy. A failed check is kept, flagged, and shown
  prominently on the Backups page.
- Start-up backup checks run once per process start. A failure is logged
  and shown to admins but doesn't block the app.
- **Backups page (admin only):** list (type, date, name, size, check status);
  Create backup (name); Download any backup or the live DB (via the backup
  API, so the copy is consistent); Delete (manual only, with confirmation);
  Restore.
- **Restore:** the admin types `RESTORE` to confirm. The app first creates a
  manual backup named "Before restore to <backup>", then copies the chosen
  backup over the live DB using the backup API. The page warns that other
  teachers should close the app first, and users whose sessions refer to
  missing accounts are signed out.
- More than 20 manual backups shows a non-blocking note suggesting a tidy-up.
- QUICKSTART notes that backups share the drive's fate, so staff should use
  Download for off-drive copies.

## 5. Logins and roles

**Schema (`users`, migrated):** `user_id`, `username` (unique,
case-insensitive), `display_name`, `email` (nullable, for future SSO),
`password_hash`, `role` (`admin` | `teacher`), `must_change_password`,
`active`, `created_at`, `last_login_at`, `failed_attempts`, `locked_until`.
The seeded placeholder admin row is deleted by migration.

**Flows:**
- No active admin exists, so a one-time "Create the first admin" page appears;
  all other routes redirect there.
- Log in, then a forced password change if `must_change_password` is set.
- Admin → Teachers: create (temporary password, forced change), reset
  password, change role, deactivate/reactivate. There's no hard delete. An
  admin can't deactivate or demote themselves if they're the last active
  admin.
- If there's only one active admin, admins see a dismissible nudge
  recommending a second one.
- `reset_admin.bat` / `reset_admin.py`: a command-line reset of a chosen
  admin's password (or creation of a new admin), for file-level recovery.

**Rules:** passwords need at least 8 characters. After 5 consecutive
failures, the account is locked for 60 seconds. Passwords are hashed with
`werkzeug.security` (scrypt/pbkdf2 default). Sessions are Flask signed
cookies with `SESSION_PERMANENT=False` and a 60-minute idle timeout,
refreshed on each request. The secret key is generated once and stored in
`_meta`, so every instance using the same DB shares it.

**CSRF:** a per-session token is required on every POST, validated in a
`before_request` hook, with templates including a hidden `csrf_token` field.
There's no new dependency.

**Permissions:**

| Capability | Teacher | Admin |
|---|:-:|:-:|
| View dashboards, analytics, heatmaps, progress, history, exports | ✓ | ✓ |
| Enter marks (single, bulk, import) | ✓ | ✓ |
| Edit/delete own entries (with reason) | ✓ | ✓ |
| Edit/delete any entry, including "Before logins" entries; restore deleted marks | | ✓ |
| Students, classes, rosters, enrolment import, subjects, outcomes | | ✓ |
| Teacher accounts, backups, restore, full change log | | ✓ |
| Change own password | ✓ | ✓ |

Everything needs sign-in except login, first-admin setup, static files and the
path-error / create-database pages. Admin-only menu items are shown greyed
out with an "Admin only" label for teachers. Every page header shows
"Signed in as <display name> (<role>)" and a Log out button.

## 6. Batches, intentional editing and the change log

**Schema:**
- `entry_batches`: `batch_id`, `kind` (`single` | `bulk` | `import`),
  `assessment_title`, `attempt_date`, `class_id` (nullable),
  `source_filename` (nullable), `created_by` (user, nullable for legacy),
  `created_at`, `deleted_at`, `deleted_by`, `delete_reason`.
- `attempts` gains `batch_id`, `entered_by` (nullable), `created_at`,
  `deleted_at`, `deleted_by`, `delete_reason`.
- `change_log`: `log_id`, `at`, `user_id`, `action` (`edit`, `delete_attempt`,
  `delete_batch`, `restore_attempt`, `restore_batch`, `restore_backup`,
  `user_admin`), `batch_id`, `attempt_id`, `before_json`, `after_json`,
  `reason`.
- **Migration of existing data:** existing attempts are grouped by (title,
  date, class) into legacy batches with `created_by = NULL`, shown as
  "Before logins" and editable by admins only.

**Ownership:** a teacher may edit or delete an attempt when `entered_by` is
their `user_id`. Batch-level delete by a teacher requires that they created
the batch.

**Correct-an-entry flow** (`/entries/<attempt_id>`):
1. Opens read-only with a "Correct…" link, shown only if permitted.
2. "Unlock to edit" enables fields: per-outcome scores, title, date, class. A
   reason is required.
3. A confirmation page shows a field-by-field diff. If nothing changed,
   nothing is saved and no log entry is written.
4. On confirm, the app updates rows in one transaction and writes a
   `change_log` entry with before/after JSON.

Editing never changes which outcomes an attempt covers. To add or drop an
outcome, delete the entry and re-enter it.

**Delete:** a single attempt needs a reason plus confirmation. A whole batch
needs a reason and typing the assessment title. Both are soft deletes and are
logged. Admin → Deleted marks lists soft-deleted attempts and batches and
restores them, which is also logged.

**My entries** (`/entries`): a teacher's own batches, newest first (title,
date, class, student count, time entered), linking to a batch page with every
row. Admins can switch to all teachers or filter by teacher.

**Duplicate warning:** before bulk or import saves, find live attempts
matching the same student, the same title (case-insensitive, trimmed) and the
same date. If any match, show a confirmation page ("N of M students already
have '<title>' on <date> (entered by X, <when>)") with Cancel as the default.
The parsed submission is carried to the confirm step as a signed hidden
payload, so the CSV doesn't need re-uploading.

**Change log views:** each entry page shows its own history. Admin → Change
log shows everything, filterable by teacher, action and date. Teachers see log
entries for their own entries.

## 7. Error handling summary

- DB locked or unreachable: clear "not saved, try again" page. The
  transaction rolls back, so nothing is ever half-saved.
- Unsafe DB location: refuse to start, with an explanation.
- Missing DB: explicit create confirmation.
- Backup failure: flagged on the Backups page and shown to admins, and
  doesn't block normal use.
- Permission denied: a 403 page saying which role is needed, with no data
  shown.
- The existing `return f"Error saving marks: {e}", 500` handlers become
  a friendly error page. Details go to the console only.

## 8. Testing

pytest goes in `requirements-dev.txt`, which isn't shipped. Tests use a temp
DB via `create_app(db_path=...)`.

1. **Characterisation tests (written before the split):** status and key
   content for every GET route on seeded demo data, re-run after the split.
2. Permission matrix: every route × {anonymous, teacher, admin} against the
   Section 5 table.
3. Soft-delete leak test: a deleted attempt must be absent from every report
   page and export.
4. Backups: simulated clock (30 starts in one day gives one daily; 14/12
   retention; manual untouched; restore creates its pre-restore backup;
   integrity flagging).
5. Imports: all-or-nothing save; duplicate warning, then confirm and cancel.
6. Migration: a copy of the pre-change demo DB upgrades with all
   attempts/scores preserved and legacy batches created.
7. Concurrency: two connections — the second writer waits and succeeds; a
   lock timeout produces the "not saved" path.
8. Path check: OneDrive / WebDAV / SharePoint paths are refused.
9. Auth: lockout, forced password change, last-admin protection, idle
   timeout, CSRF rejection.

**Manual checklist (`docs/SHARED_DRIVE_TRIAL.md`)**, run by Nathan on the
school drive: two PCs and two accounts saving at the same moment; the
wrong-folder refusal; backup creation and restore; teacher vs admin
permissions.

## 9. Build order

Each stage leaves a working app and gets its own commit:

1. Characterisation tests, then the code split and class-label helper.
2. Database layer: pragmas, path check, create-confirm, versioned migrations,
   live views.
3. Backups (before stages 4–5, so their migrations are backed up).
4. Logins, roles, CSRF, teacher admin, `reset_admin`.
5. Batches, editing, deleted marks, change log, duplicate warning.
6. Release build and launcher update, `serve.py`, QUICKSTART update, the
   shared-drive trial checklist.
