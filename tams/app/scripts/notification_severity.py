# app/scripts/notification_severity.py

NOTIFICATION_SEVERITY_MAP = {
    # Cursos
    "course_created":   "notice",
    "course_updated":   "notice",

    # Requests / acciones operativas
    "pickup_request":   "warning",

    # Problemas graves
    "assets_overdue":   "critical",
    "assets_lost":      "critical",
}
