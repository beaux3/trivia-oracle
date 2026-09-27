"""
Copy qbreader tossups into the local SQLite database.

    python -m trivia_questions.local.sync                 # every set not synced yet
    python -m trivia_questions.local.sync --limit 5       # only the next 5 (newest first)
    python -m trivia_questions.local.sync --sets "2023 ACF Winter" "2024 ACF Fall"
    python -m trivia_questions.local.sync --refresh       # download synced sets again

Crawls /set-list, then /num-packets and /packet?questionTypes=tossups for each
set. Each set is stored in one transaction and only marked synced once every
packet is in, so an interrupted run resumes by running the same command again.
Requests are sequential with a pause between them, far below qbreader's
20 requests/second limit.
"""
import argparse
import logging
import os
import sys
import time

import requests

from .db import connect, replace_set, synced_set_names

# Same default the bot uses: QUESTIONS_DB, else <repo root>/data/questions.db.
DEFAULT_DB = os.environ.get("QUESTIONS_DB") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "questions.db"
)

API_URL = "https://www.qbreader.org/api"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class QbreaderClient:
    def __init__(self, delay: float, attempts: int = 5):
        self.delay = delay
        self.attempts = attempts
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "trivia-oracle-sync"
        self._last_request = 0.0

    def get(self, endpoint: str, **params) -> dict:
        for attempt in range(1, self.attempts + 1):
            wait = self._last_request + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                response = self.session.get(f"{API_URL}/{endpoint}", params=params, timeout=30)
                if response.status_code not in RETRY_STATUSES:
                    response.raise_for_status()
                    return response.json()
                error = f"HTTP {response.status_code}"
            except requests.ConnectionError as e:
                error = str(e)
            except requests.Timeout:
                error = "timed out"
            if attempt < self.attempts:
                backoff = 2 ** attempt
                logging.warning("%s %s failed (%s); retrying in %ds", endpoint, params, error, backoff)
                time.sleep(backoff)
        raise RuntimeError(f"{endpoint} {params} failed after {self.attempts} attempts: {error}")

    def set_names(self) -> list:
        return self.get("set-list")["setList"]

    def packet_count(self, set_name: str) -> int:
        return self.get("num-packets", setName=set_name)["numPackets"]

    def packet_tossups(self, set_name: str, packet_number: int) -> list:
        return self.get("packet", setName=set_name, packetNumber=packet_number, questionTypes="tossups")["tossups"]


def sync_set(client: QbreaderClient, conn, set_name: str) -> int:
    packet_count = client.packet_count(set_name)
    tossups = []
    for packet_number in range(1, packet_count + 1):
        tossups += client.packet_tossups(set_name, packet_number)
    return replace_set(conn, set_name, packet_count, tossups)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Copy qbreader tossups into the local question database.")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"database file (default: {DEFAULT_DB})")
    parser.add_argument("--sets", nargs="+", metavar="NAME", help="sync only these sets")
    parser.add_argument("--limit", type=int, help="sync at most this many sets")
    parser.add_argument("--refresh", action="store_true", help="also re-download sets already synced")
    parser.add_argument("--delay", type=float, default=0.2, help="seconds between requests (default: 0.2)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = QbreaderClient(delay=args.delay)
    conn = connect(args.db)

    names = args.sets or client.set_names()
    if not args.refresh:
        done = synced_set_names(conn)
        names = [n for n in names if n not in done]
    if args.limit is not None:
        names = names[:args.limit]

    logging.info("Syncing %d set(s) into %s", len(names), args.db)
    failed = []
    for i, name in enumerate(names, 1):
        try:
            count = sync_set(client, conn, name)
        except Exception as e:
            logging.error("[%d/%d] %s: %s", i, len(names), name, e)
            failed.append(name)
            continue
        logging.info("[%d/%d] %s: %d tossups", i, len(names), name, count)

    total_sets, total_tossups = conn.execute("SELECT COUNT(*), COALESCE(SUM(tossup_count), 0) FROM sets").fetchone()
    conn.close()
    logging.info("Database now holds %d sets, %d tossups", total_sets, total_tossups)
    if failed:
        logging.error("%d set(s) failed; rerun to retry: %s", len(failed), ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
