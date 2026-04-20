# TAMS Agent Context

## Purpose
TAMS is an internal asset-management app for training operations. The main business domains are:

- courses
- devices and asset types
- card/PC assignments to courses
- alerts and notifications between TCO and ITC Support
- temporary card loans
- NFC-based login through a local client agent

## Real Entry Points
- `wsgi.py`: main Flask app entry point. `create_app()` lives in [`app/__init__.py`](/C:/Users/adrian/SIA/tams/app/__init__.py).
- `main.py`: separate FastAPI app with a small CRUD API. It is not the main web UI and appears auxiliary/legacy.
- `client_agent/nfc_agent.py`: local desktop agent that reads NFC on each client PC and exposes localhost HTTP for the browser.

## Architecture Summary
- Framework: Flask 3 for the main app, Jinja templates, Flask-Login, Flask-Bcrypt.
- ORM layer: Flask-SQLAlchemy models in [`app/models.py`](/C:/Users/adrian/SIA/tams/app/models.py).
- DB access pattern: most routes use `SessionLocal` from [`app/db.py`](/C:/Users/adrian/SIA/tams/app/db.py), not `db.session`.
- Database: PostgreSQL, hardcoded locally in `app/db.py`.
- Templates: `app/templates/`.
- Static assets: `app/static/`.

## Important Constraint
The codebase mixes two SQLAlchemy access styles:

- `app.extensions.db` / Flask-SQLAlchemy
- `SessionLocal` / plain SQLAlchemy session

Do not casually mix ORM objects from different sessions in the same operation. The app already documents this risk in `app/__init__.py`.

## Module Map
- `app/main/routes.py`: dashboard, counters, alert summaries, pickup widgets.
- `app/auth/routes.py`: username/password login, NFC login, UID normalization.
- `app/courses/routes.py`: largest business module; course CRUD, exports, ITC requirements, notifications, calendar helpers, PC return flows.
- `app/devices/routes.py`: device CRUD, role-based visibility, asset type hierarchy, exports.
- `app/assignments/routes.py`: single and bulk assign/return flows plus movement logging.
- `app/notifications/routes.py`: department-scoped inbox and status transitions.
- `app/alerts/` and `app/scripts/alerts_*`: alert generation and filtering.
- `app/temporary_loans/`: temporary card loan API and service logic.
- `app/api/routes.py`: small JSON endpoints used by the UI for counters and lookups.

## Domain Rules That Matter
- TCO mainly manages card assets.
- ITC Support mainly manages non-card assets, especially computers.
- Asset visibility is role/department-scoped in route logic, not just templates.
- Asset types are hierarchical. Roots such as `CARD`, `COMPUTER`, `USB` control subtype behavior.
- Some asset types require RFID, some require barcode, and forms enforce that dynamically.
- Assignments often imply device status transitions: `available` <-> `assigned`.
- Notifications are department-targeted and unread logic depends on both `read_at` and status.
- Alerts are derived data assembled from services/scripts, not a single table.

## Before Editing
Read these first:

1. [`docs/context/architecture.md`](/C:/Users/adrian/SIA/tams/docs/context/architecture.md)
2. [`docs/context/domain-flows.md`](/C:/Users/adrian/SIA/tams/docs/context/domain-flows.md)
3. [`docs/context/change-safety.md`](/C:/Users/adrian/SIA/tams/docs/context/change-safety.md)

## Practical Startup
- Main app: `python wsgi.py`
- FastAPI auxiliary app: `python main.py`
- Client NFC agent: `cd client_agent && python nfc_agent.py`

## Current Gaps
- No root `README.md` existed when this context was written.
- No automated test suite was found in the repo.
- Some files still contain legacy/experimental code paths and mixed conventions.
