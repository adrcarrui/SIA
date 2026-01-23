from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(dt):
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reason_counts_for_calendar(reason: Dict[str, Any], now_utc: Optional[datetime] = None) -> bool:
    """Return True if this *reason* should affect calendar coloring/borders.

    Rules:
      - open -> counts
      - snoozed -> counts only if snooze_until has passed
      - acked / ignored -> does not count

    Note: legacy code may store the state in "state"; newer code may use "status".
    """
    now_utc = now_utc or _utcnow()

    st = (reason.get("status") or reason.get("state") or "open").strip().lower()
    if st == "open":
        return True

    if st == "snoozed":
        until = _as_aware_utc(reason.get("snooze_until"))
        # If no until, be conservative: treat as snoozed (does NOT count)
        if not until:
            return False
        return until <= now_utc

    return False


def _contains(text: Any, q: str) -> bool:
    if not q:
        return True
    if text is None:
        return False
    return q.lower() in str(text).lower()


def filter_alerts(
    alerts: List[Dict[str, Any]],
    *,
    severity: str = "",
    type_q: str = "",
    q: str = "",
    responsible: str = "",
    state: str = "",
    course_q: str = "",
    include_hidden: bool = False,
    **_ignored: Any,
) -> List[Dict[str, Any]]:
    """Backwards-compatible filtering used by app/alerts/routes.py.

    This is intentionally defensive: routes historically passed lots of kwargs.
    """
    sev = (severity or "").strip().lower()
    st_filter = (state or "").strip().lower()
    qn = (q or "").strip().lower()
    cq = (course_q or "").strip().lower()
    type_set = {t.strip() for t in (type_q or "").split(",") if t.strip()}

    out: List[Dict[str, Any]] = []
    now_utc = _utcnow()

    for a in alerts or []:
        if type_set and (a.get("type") or "") not in type_set:
            continue

        # course filter
        course = a.get("course")
        course_code = getattr(course, "course", None) if course else None
        course_name = getattr(course, "name", None) if course else None
        if cq and not (_contains(course_code, cq) or _contains(course_name, cq)):
            continue

        # responsible filter (best effort)
        if responsible:
            rid = getattr(course, "responsible_id", None) if course else None
            if str(rid or "") != str(responsible).strip():
                continue

        # free-text filter (message + course)
        if qn:
            if not (
                _contains(a.get("message"), qn)
                or _contains(a.get("code"), qn)
                or _contains(a.get("type"), qn)
                or _contains(course_code, qn)
                or _contains(course_name, qn)
            ):
                # try inside reasons
                reasons_hay = " ".join(
                    str((r.get("text") or r.get("message") or ""))
                    for r in (a.get("reasons") or [])
                ).lower()
                if qn not in reasons_hay:
                    continue

        reasons = a.get("reasons") or []
        new_reasons: List[Dict[str, Any]] = []

        for r in reasons:
            r_st = (r.get("status") or r.get("state") or "open").strip().lower()
            if st_filter and r_st != st_filter:
                continue

            if sev:
                r_sev = (r.get("severity") or a.get("severity") or "").strip().lower()
                if r_sev != sev:
                    continue

            if not include_hidden:
                if not reason_counts_for_calendar(r, now_utc=now_utc) and r_st in ("ignored", "snoozed"):
                    # ignored/snoozed (not expired) are considered hidden for the alerts list
                    continue

            new_reasons.append(r)

        if reasons and not new_reasons:
            continue

        aa = dict(a)
        if reasons:
            aa["reasons"] = new_reasons
        out.append(aa)

    return out
