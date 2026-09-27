"""
Shared harness for the integration tests.

Runs the real backend service (server.build_app over a real SQLite database) on
a loopback port in a background thread, so the bot's HTTP client and game code
talk to it exactly as they do in Docker Compose. Only qbreader.org is replaced,
by ScriptedJudge, so the tests need no network.
"""
import asyncio
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Optional

from aiohttp import web

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")

from trivia_oracle_backend.local import LocalQuestionSource
from trivia_oracle_backend.local.db import connect, replace_set
from trivia_oracle_backend.server import build_app


def tossup(id, category="Science", subcategory="Biology", alt=None, difficulty=8,
           question=None, answer=None, set_name="Test Set", packet=1, answerline=None):
    """
    A qbreader-shaped tossup object, as sync.py stores them.

    `answerline` is the answer as HTML, directives and all; by default the answer is just underlined.
    """
    answer = answer or id
    return {
        "_id": id,
        "set": {"_id": "set-" + set_name, "name": set_name, "year": 2024, "standard": True},
        "packet": {"_id": f"p{packet}", "name": f"Packet {packet}", "number": packet},
        "number": 1,
        "category": category,
        "subcategory": subcategory,
        "alternate_subcategory": alt,
        "difficulty": difficulty,
        "question": question or f"First clue for {id}. Second clue for {id}.",
        "question_sanitized": question or f"First clue for {id}. Second clue for {id}.",
        "answer": answerline or f"<b><u>{answer}</u></b>",
        "answer_sanitized": re.sub(r"<[^>]+>", "", answerline) if answerline else answer,
        "updatedAt": "2024-01-01T00:00:00.000Z",
    }


@dataclass(frozen=True)
class Verdict:
    directive: str
    directed_prompt: Optional[str] = None


class ScriptedJudge:
    """Stands in for qbreader's checker: the given text picks the directive."""

    def __init__(self):
        self.calls = []

    async def check(self, answerline: str, given: str) -> Verdict:
        self.calls.append((answerline, given))
        if given == "boom":
            raise RuntimeError("qbreader down")
        if given == "more specific":
            return Verdict("prompt", "the full name")
        if given.strip().lower() == re.sub(r"<[^>]+>", "", answerline).lower():
            return Verdict("accept")
        return Verdict("reject")


class BackendServer:
    """The backend service on 127.0.0.1:<free port>, served from its own thread and event loop."""

    def __init__(self, source, judge, backend_name="local", custom_source=None):
        self._app = build_app(source, judge, backend_name, custom_source=custom_source)
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self.url = None

    def _serve(self):
        asyncio.set_event_loop(self._loop)
        runner = web.AppRunner(self._app)
        self._loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, "127.0.0.1", 0)
        self._loop.run_until_complete(site.start())
        self.url = f"http://127.0.0.1:{runner.addresses[0][1]}"
        self._ready.set()
        self._loop.run_forever()
        self._loop.run_until_complete(runner.cleanup())
        self._loop.close()

    def start(self):
        self._thread.start()
        if not self._ready.wait(10):
            raise RuntimeError("backend did not start")
        return self

    def stop(self):
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(10)


class LocalStack:
    """
    A temporary questions.db behind a running backend service.

    `custom_tossups`, if given, fill a second database that serves the custom questions.
    """

    def __init__(self, tossups, judge=None, custom_tossups=None):
        self.judge = judge or ScriptedJudge()
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "questions.db")
        conn = connect(self.db_path)
        replace_set(conn, "Test Set", 1, tossups)
        conn.close()
        self.custom_db_path = os.path.join(self._tmp.name, "custom_questions.db")
        if custom_tossups:
            conn = connect(self.custom_db_path)
            replace_set(conn, "Custom Set", 1, custom_tossups, custom=True)
            conn.close()
        # The custom database file is opened per request, so without custom_tossups it simply does not exist.
        self.server = BackendServer(
            LocalQuestionSource(self.db_path), self.judge, custom_source=LocalQuestionSource(self.custom_db_path),
        ).start()
        self.url = self.server.url

    def close(self):
        self.server.stop()
        self._tmp.cleanup()


def wait_until(condition, timeout=10.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False
