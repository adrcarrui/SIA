"""TAMS NFC Agent (distributed PC/SC readers).

Browsers can't talk to PC/SC readers. If the *server* reads the reader, every
client PC ends up sharing it (and logins get "broadcast" by accident).

This agent runs on EACH client PC, reads the local reader, and exposes a tiny
HTTP API on localhost so the web UI can fetch the UID.

Endpoints:
  GET /health  -> {"ok": true, "reader": "..."}
  GET /uid     -> {"success": true, "uid": "04AABBCCDD"} or
                   {"success": false, "reason": "no_card"}

Default bind: 127.0.0.1:8765 (localhost only).

Install:
  pip install Flask pyscard

Run:
  python nfc_agent.py

Optional env vars:
  TAMS_NFC_PORT=8765
  TAMS_NFC_READER_INDEX=0

Notes:
- This uses the common APDU "FF CA 00 00 00" (GET DATA UID) supported by ACR122
  and many similar readers.
- If you have a different reader/card type that doesn't support it, you'll need
  a reader-specific APDU.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

from flask import Flask, jsonify, make_response, request

try:
    from smartcard.System import readers
    from smartcard.Exceptions import CardConnectionException, NoCardException
except Exception as e:  # pragma: no cover
    readers = None
    CardConnectionException = Exception  # type: ignore
    NoCardException = Exception  # type: ignore
    _import_error = e
else:
    _import_error = None


APP = Flask(__name__)

PORT = int(os.environ.get("TAMS_NFC_PORT", "8765"))
READER_INDEX = int(os.environ.get("TAMS_NFC_READER_INDEX", "0"))

# APDU to request UID for many PC/SC contactless readers (ACR122 etc.)
APDU_GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]


def _add_cors(resp):
    # Allow web UI to call localhost.
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@APP.after_request
def after_request(resp):
    return _add_cors(resp)


@APP.route("/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return _add_cors(make_response("", 204))

    if _import_error is not None or readers is None:
        return jsonify({"ok": False, "error": f"pyscard not available: {_import_error}"}), 500

    try:
        rlist = readers()
        if not rlist:
            return jsonify({"ok": False, "error": "No PC/SC readers found"}), 404
        idx = min(max(READER_INDEX, 0), len(rlist) - 1)
        return jsonify({"ok": True, "reader": str(rlist[idx]), "readers": [str(r) for r in rlist]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _pick_reader() -> Tuple[Optional[object], Optional[str]]:
    if _import_error is not None or readers is None:
        return None, f"pyscard not available: {_import_error}"

    rlist = readers()
    if not rlist:
        return None, "No PC/SC readers found"

    idx = min(max(READER_INDEX, 0), len(rlist) - 1)
    return rlist[idx], None


def _read_uid_once() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Returns (uid_hex, reason, error_message)."""

    reader, rerr = _pick_reader()
    if not reader:
        return None, "no_reader", rerr

    try:
        conn = reader.createConnection()
        conn.connect()  # will raise NoCardException if no card
        data, sw1, sw2 = conn.transmit(APDU_GET_UID)
        if (sw1, sw2) != (0x90, 0x00):
            return None, "apdu_error", f"APDU failed: SW1={sw1:02X} SW2={sw2:02X}"
        uid = "".join(f"{b:02X}" for b in data)
        if not uid:
            return None, "no_uid", "Empty UID"
        return uid, None, None
    except NoCardException:
        return None, "no_card", None
    except CardConnectionException as e:
        return None, "conn_error", str(e)
    except Exception as e:
        return None, "agent_error", str(e)
    
    finally:
        try:
            if conn is not None:
                conn.disconnect()
        except Exception:
            pass


@APP.route("/uid", methods=["GET", "OPTIONS"])
def uid():
    if request.method == "OPTIONS":
        return _add_cors(make_response("", 204))

    uid_hex, reason, err = _read_uid_once()
    if uid_hex:
        return jsonify({"success": True, "uid": uid_hex})

    # keep response stable for frontends
    payload = {"success": False, "reason": reason or "agent_error"}
    if err:
        payload["error"] = err
    return jsonify(payload)


if __name__ == "__main__":
    # localhost only. Don't bind to 0.0.0.0 unless you *want* others to read your badges.
    APP.run(host="127.0.0.1", port=PORT, debug=False)
