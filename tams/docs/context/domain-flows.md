# TAMS Domain Flows

## 1. Authentication and NFC Login
- Standard login is handled in [`app/auth/routes.py`](/C:/Users/adrian/SIA/tams/app/auth/routes.py).
- Password flow supports two cases:
  - bcrypt hashes
  - legacy plaintext values in `password_hash`, which are re-hashed on successful login
- NFC login flow:
  1. browser talks to local client agent on `127.0.0.1`
  2. agent reads UID from the local reader
  3. browser posts UID to `/auth/nfc-login`
  4. server normalizes UID and logs the user in

## 2. Courses
- Main implementation is in [`app/courses/routes.py`](/C:/Users/adrian/SIA/tams/app/courses/routes.py).
- This is the densest business module in the repo.
- It handles:
  - course CRUD
  - date validation
  - TCO and ITC statuses
  - TCO responsibles
  - ITC asset requirements per course
  - exports
  - ITC notification generation
  - PC lookup and return flows

### Status model
- TCO statuses: `planned`, `active`, `finished`, `cancelled`
- ITC statuses: `start`, `cancel or error`, `completed`, `delivered`, `end`, `collected`, `RT delivered`, `loan`, `MSN loaded`, `MSN delivered`
- `Course.auto_status` computes a derived TCO-like state from dates.

## 3. Devices and Asset Types
- Main implementation is in [`app/devices/routes.py`](/C:/Users/adrian/SIA/tams/app/devices/routes.py).
- Devices rely on `AssetType` hierarchy.
- The code distinguishes:
  - root types
  - child subtypes
  - legacy `Device.type` mapping for older records

### Important behavior
- Some subtypes require RFID.
- Some subtypes require barcode.
- Root types with active children are not valid final selections in forms.
- TCO generally sees/manages only `CARD` family.
- ITC Support generally sees/manages non-`CARD` families.

## 4. Assignments
- Main implementation is in [`app/assignments/routes.py`](/C:/Users/adrian/SIA/tams/app/assignments/routes.py).
- Flows include:
  - single assignment creation
  - bulk assignment from course screens
  - bulk return by UID input
  - bulk return by selected assignment IDs

### Operational expectations
- Creating an active assignment normally sets device status to `assigned`.
- Returning/closing assignments usually sets the device back to `available`.
- Some return flows mark assignments closed; others delete assignment rows entirely.
- Movement logging is expected around assignment changes.

## 5. Notifications
- Main implementation is in [`app/notifications/routes.py`](/C:/Users/adrian/SIA/tams/app/notifications/routes.py).
- Notifications are scoped by department unless the actor is admin.
- "Unread" is not a simple boolean:
  - `read_at is null`
  - status is not `done` or `dismissed`

### Common statuses
- `open`
- `in_progress`
- `done`
- `dismissed`

## 6. Alerts
- Alerts are not just rows from one table.
- Generation/filtering lives in:
  - `app/scripts/alerts_service.py`
  - `app/scripts/alert_filters.py`
  - `app/scripts/get_overdue_assignments.py`
  - `app/alerts/`
- `AlertState` stores per-course alert lifecycle state, especially visibility/snooze semantics.
- Dashboard counts and calendar counts rely on filtered alert reasons, not only top-level alert objects.

## 7. Temporary Card Loans
- API routes: [`app/temporary_loans/routes.py`](/C:/Users/adrian/SIA/tams/app/temporary_loans/routes.py)
- Domain service: [`app/temporary_loans/service.py`](/C:/Users/adrian/SIA/tams/app/temporary_loans/service.py)
- Main actions:
  - create temporary loan
  - mark returned
  - mark lost
  - refresh overdue state

## 8. Dashboard and Counters
- Main dashboard logic is in [`app/main/routes.py`](/C:/Users/adrian/SIA/tams/app/main/routes.py).
- `/api/counters` provides lightweight counts for polling.
- Session refresh intentionally skips `/api/counters` polling, so background polling does not keep sessions alive.
