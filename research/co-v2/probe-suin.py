#!/usr/bin/env python3
"""Is SUIN-Juriscol answering? Run before anything else touches Colombia.

The failure mode this exists for is specific and misleading: TCP connects,
TLS negotiates, and then the server sends zero HTTP bytes. curl reports
"(52) Empty reply from server", a browser reports ERR_EMPTY_RESPONSE, and
nothing in either message says whether the cause is an outage, a geo-block,
or our own client.

It separates the three by asking four questions in order:

  1. Does SUIN answer us?
  2. Does another Colombian government host answer us?  (route to .co)
  3. Does an independent network reach SUIN?             (geo-block)
  4. When did the Internet Archive last get a byte?      (how long)

Exit 0 if SUIN answers, 1 if it does not. No SUIN traffic beyond 2 requests.

    python3 probe-suin.py
"""

from __future__ import annotations

import json
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

SUIN = "https://www.suin-juriscol.gov.co"
# A .gov.co host on Colombian address space, not behind a global CDN — so a
# failure here means the route is broken, not that SUIN is.
CONTROL = "http://www.secretariasenado.gov.co/senado/basedoc/constitucion_politica_1991.html"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

# SUIN serves an incomplete certificate chain, so a TLS failure here says
# nothing about availability. Verification is off for the probe only.
_LAX = ssl.create_default_context()
_LAX.check_hostname = False
_LAX.verify_mode = ssl.CERT_NONE


def get(url: str, timeout: int = 25) -> tuple[int | None, int, str]:
    """Return (status, bytes, note). status None means no HTTP response."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_LAX) as r:
            return r.status, len(r.read(4096)), "ok"
    except urllib.error.HTTPError as e:
        return e.code, 0, "http error"
    except Exception as e:  # noqa: BLE001 — the point is to report, not classify
        return None, 0, f"{type(e).__name__}: {e}"


def recent_archive_captures(days: int = 30) -> tuple[int, str | None]:
    """(captures in the last `days`, newest date seen) from the Internet Archive.

    CDX sorts by urlkey, not by time, so "the last row" is not the newest
    capture — asking for a time window and taking the max is the only honest
    way to read this. The Archive crawls from US datacenters continuously; if
    it has nothing recent either, SUIN is not merely blocking us.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y%m%d")
    url = (
        "http://web.archive.org/cdx/search/cdx?url=suin-juriscol.gov.co"
        f"&matchType=domain&fl=timestamp&from={since}&limit=5000"
    )
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            rows = [x.strip() for x in r.read().decode().split("\n") if x.strip()]
    except Exception:  # noqa: BLE001
        return -1, None
    if not rows:
        return 0, None
    ts = max(rows)
    return len(rows), f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"


def main() -> int:
    print(f"probe-suin  ·  {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")

    status, n, note = get(f"{SUIN}/")
    print(f"1. SUIN root                 → {status or 'NO HTTP RESPONSE'} ({n} bytes) {note}")
    suin_up = status is not None

    status2, n2, note2 = get(f"{SUIN}/viewDocument.asp?id=1789030")
    print(f"2. SUIN viewDocument (LEY-57-1887) → {status2 or 'NO HTTP RESPONSE'} ({n2} bytes)")
    suin_up = suin_up or status2 is not None

    status3, n3, _ = get(CONTROL)
    print(f"3. control: secretariasenado.gov.co → {status3 or 'NO HTTP RESPONSE'} ({n3} bytes)")

    n_cap, cap = recent_archive_captures()
    if n_cap < 0:
        print("4. Internet Archive               → could not be queried")
    elif n_cap == 0:
        print("4. Internet Archive, last 30 days → NOTHING CAPTURED")
    else:
        print(f"4. Internet Archive, last 30 days → {n_cap} captures, newest {cap}")

    print()
    if suin_up:
        print("VERDICT: SUIN answers. Proceed.")
        return 0
    if status3 is None:
        print("VERDICT: SUIN silent AND the control host is silent — suspect the local")
        print("         network, not the source. Re-run from elsewhere before concluding.")
        return 1
    print("VERDICT: SUIN is silent while another Colombian government host answers, so")
    print("         the route to Colombia is fine.")
    if n_cap == 0:
        print("         The Archive got nothing in 30 days either: SUIN is down for")
        print("         everyone. A VM in another region buys nothing. Do not raise one,")
        print("         and do not start a fetch.")
    elif n_cap > 0:
        print(f"         But the Archive IS getting through ({n_cap} captures, newest {cap}),")
        print("         so this looks like a block on our address, not an outage.")
        print("         Fetching from another region is worth trying.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
