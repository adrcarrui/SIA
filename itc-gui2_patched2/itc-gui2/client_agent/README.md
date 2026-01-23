# TAMS NFC Agent (Option 1: distributed PC/SC readers)

Because web browsers can't read PC/SC readers, each client PC runs a local agent
that reads the UID and exposes it on `http://127.0.0.1:8765`.

The server (DB machine) **does not** read any reader.

## Install (Windows)
1. Install the reader driver (and make sure the reader shows up in Windows).
2. Install Python 3.10+.
3. In a terminal:

```bat
cd client_agent
pip install -r requirements.txt
python nfc_agent.py
```

You should see something like:
- `Running on http://127.0.0.1:8765`

Test:
- Open `http://127.0.0.1:8765/health`

## Browser + CORS
The agent allows CORS from any origin, but it only binds to localhost.

## Config
Environment variables:
- `TAMS_NFC_PORT` (default 8765)
- `TAMS_NFC_READER_INDEX` (default 0)

## If your web app is HTTPS
Most browsers block calling `http://127.0.0.1` from an `https://` page (mixed content).
For intranet use, keep the web app on HTTP, or run the agent with HTTPS.
(HTTPS support is not included in this minimal agent.)
