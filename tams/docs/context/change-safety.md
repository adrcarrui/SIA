# TAMS Change Safety

## Read This Before Touching Business Logic

## 1. Session Safety
- Most routes use `SessionLocal`, even though models come from Flask-SQLAlchemy.
- Avoid passing ORM instances between `SessionLocal` and `db.session`.
- If you change request lifecycle or helper functions, confirm which session owns the objects.

## 2. Department and Role Rules Are Enforced in Python
- Visibility and authorization are often coded directly in route functions.
- Changing UI filters without matching route changes will create leaks or broken behavior.
- Check at least:
  - `app/devices/routes.py`
  - `app/main/routes.py`
  - `app/notifications/routes.py`
  - `app/api/routes.py`

## 3. Asset Type Hierarchy Is Central
- Do not treat `Device.type` as the source of truth for new work.
- Current behavior depends on `AssetType` roots and children.
- A change to asset type rules can affect:
  - device forms
  - dashboard counts
  - PC/card lookup APIs
  - course requirements

## 4. Assignments Are Not Uniform
- Some flows close assignments with `released_at` and `status = closed`.
- Some flows delete assignment rows after return.
- Before changing assignment semantics, inspect all return flows in `app/assignments/routes.py` and `app/courses/routes.py`.

## 5. Notifications and Alerts Are Different Systems
- Notifications are stored work items for departments.
- Alerts are derived operational warnings with optional persisted state.
- Do not merge their logic casually; dashboard badges rely on both systems differently.

## 6. NFC Architecture Assumption
- The server should not directly access the PC/SC reader in the distributed setup.
- Browser -> local agent -> server is the intended model.
- Changes to login/NFC flows should preserve this multi-PC assumption.

## 7. Legacy/Transition Areas
- `main.py` FastAPI app appears separate from the Flask web app.
- `Device.type` is legacy compatibility data.
- Login still supports plaintext-to-bcrypt migration.
- Some modules contain debug prints and mixed English/Spanish conventions.

## 8. Recommended First Reads For Any Non-Trivial Task
1. `AGENTS.md`
2. `app/models.py`
3. the relevant route module
4. any service/helper in `app/scripts/` or feature-specific service modules

## 9. Verification Checklist
- If you touched device or assignment logic, verify status transitions.
- If you touched department-scoped features, verify TCO, ITC Support, and admin behavior separately.
- If you touched dashboard counts, check both template context processors and `/api/counters`.
- If you touched alerts or notifications, verify badge logic as well as list/detail behavior.
