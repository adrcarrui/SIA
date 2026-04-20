# TAMS Architecture

## High-Level Shape
TAMS is primarily a server-rendered Flask application with Jinja templates. A smaller FastAPI app exists in parallel, but the main operational product is the Flask app launched from `wsgi.py`.

## Runtime Components

### Flask app
- Factory: [`app/__init__.py`](/C:/Users/adrian/SIA/tams/app/__init__.py)
- Entry point: [`wsgi.py`](/C:/Users/adrian/SIA/tams/wsgi.py)
- Blueprints registered:
  - `auth`
  - `main`
  - `users`
  - `courses`
  - `devices`
  - `movements`
  - `assignments`
  - `asset_types`
  - `notifications`
  - `alerts`
  - `api`
  - `temporary_loans`

### Auxiliary FastAPI app
- Entry point: [`main.py`](/C:/Users/adrian/SIA/tams/main.py)
- Contains CRUD endpoints for users, courses, and devices.
- Uses the same DB engine but is structurally separate from the Flask UI.

### NFC local agent
- Path: [`client_agent/nfc_agent.py`](/C:/Users/adrian/SIA/tams/client_agent/nfc_agent.py)
- Purpose: read each PC's local NFC reader and expose UID over localhost.
- Reason: browsers cannot access PC/SC directly, and the server must not own the reader in a multi-PC setup.

## Data Layer

### ORM and sessions
- Models are defined with Flask-SQLAlchemy in [`app/models.py`](/C:/Users/adrian/SIA/tams/app/models.py).
- The app frequently queries with `SessionLocal` from [`app/db.py`](/C:/Users/adrian/SIA/tams/app/db.py).
- `app/__init__.py` explicitly warns that `SessionLocal` is a separate session from `sqla_db.session`.

### Database configuration
- Engine and `SessionLocal` live in [`app/db.py`](/C:/Users/adrian/SIA/tams/app/db.py).
- `DATABASE_URL` is currently hardcoded to local PostgreSQL.
- The app assumes existing tables; schema creation is not the default runtime path.

## Core Data Model

### Users
- Authenticated with Flask-Login.
- Can log in by password or NFC UID.
- Important fields: `username`, `password_hash`, `uid`, `role`, `department`, `active`.

### Devices
- Represent physical assets.
- Important fields: `uid`, `barcode`, `status`, `type` legacy field, `asset_type_id`.
- Device subtype behavior depends on `AssetType`.

### AssetType
- Hierarchical taxonomy.
- Root nodes like `CARD`, `COMPUTER`, `USB` shape UI filtering and business rules.
- Flags `requires_rfid`, `requires_barcode`, `show_in_calendar` matter in forms and lookups.

### Course
- Main training/tracking entity.
- Has both TCO and ITC status fields.
- Can have responsible user and asset requirements.

### Assignment
- Links a device to a course.
- Usually drives device status changes and stock availability.
- Also supports temporary assignments via `is_temporary`.

### Notification
- Inbox item targeted to a department.
- Uses `severity`, `status`, `read_at`, `active`.
- Department filtering is enforced in route logic.

### AlertState
- Persistence for alert lifecycle state such as `open`, `ack`, `snoozed`, `resolved`.
- Alert generation itself is still service-driven.

### TemporaryCardLoan
- Tracks temporary card replacements and return/lost flows.

## Template/UI Shape
- Shared layout: [`app/templates/base.html`](/C:/Users/adrian/SIA/tams/app/templates/base.html)
- Dashboard: [`app/templates/index.html`](/C:/Users/adrian/SIA/tams/app/templates/index.html)
- Partial refresh endpoints exist for dashboard widgets and counters.
- The app is mostly server-rendered, with small AJAX JSON helpers under `/api`.

## Cross-Cutting Services
- Movement logging is used across modules for audit trails.
- Alert logic is spread across `app/scripts/alerts_*`, `alert_filters.py`, and alert routes/services.
- Notification creation is often triggered from course changes and operational workflows.

## What Future Agents Should Assume
- Route modules contain substantial business logic, not just HTTP wiring.
- Status names are business-significant and reused in filters, counters, and templates.
- Department and role checks are duplicated in multiple modules; changing permissions usually requires multi-file edits.
