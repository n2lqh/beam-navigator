"""QRZ XML Data client, spec 1.34 (requirements 4.9; decision 29).

HTTPS POST, so the password is never in a URL. One login per session; the key is kept in
memory only. A Session Timeout gets exactly one fresh login and one repeat, never a loop.
The client holds no database connection, so it is safe to call from a worker thread.
"""

import threading
from collections.abc import Callable
from http.client import HTTPException
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from beam_navigator import __version__
from beam_navigator.core.qrz import MAX_REPLY, QrzRecord, QrzResponse, QrzSession, parse_response
from beam_navigator.qrz_login import LoginUnavailable, load_login

URL = "https://xmldata.qrz.com/xml/current/"
TIMEOUT_S = 5.0
OFFLINE = "QRZ can't be reached. Everything else works offline."
NO_LOGIN = "Set up your QRZ login in Settings → QRZ."
REFUSED = "QRZ refused service for this login; try again tomorrow."
NON_SUBSCRIBER = "Your QRZ login has no XML Data subscription, so QRZ sends limited data."
NOT_FOUND = "QRZ has no record for"  # followed by the call: "QRZ has no record for K1X."

Transport = Callable[[str, dict[str, str]], bytes]


class QrzError(Exception):
    """A plain message for the operator. It never contains the password."""


def https_post(url: str, fields: dict[str, str]) -> bytes:
    request = Request(
        url,
        data=urlencode(fields).encode("ascii"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 (fixed https URL)
        data: bytes = response.read(MAX_REPLY + 1)
        return data


def default_agent() -> str:
    return f"BeamNav{__version__}"


class QrzClient:
    def __init__(self, transport: Transport = https_post, agent: str | None = None) -> None:
        self._transport = transport
        self._agent = agent or default_agent()
        self._key: str | None = None
        self._refused = False
        self._password = ""
        self._forget = False  # set without the lock, so the UI never waits on a lookup
        self._lock = threading.Lock()

    def _scrub(self, text: str) -> str:
        return text.replace(self._password, "***") if self._password else text

    def _post(self, fields: dict[str, str]) -> QrzResponse:
        try:
            data = self._transport(URL, fields)
        except (OSError, HTTPException):  # URLError, timeouts, DNS, broken HTTP replies
            raise QrzError(OFFLINE) from None
        try:
            return parse_response(data)
        except ValueError as exc:
            raise QrzError(str(exc)) from None

    def _check_refused(self, session: QrzSession) -> None:
        if session.error and session.error.strip().lower() == "connection refused":
            self._refused = True
            raise QrzError(REFUSED)

    def forget_session(self) -> None:
        """After the saved login changes or is cleared: the next call logs in afresh.
        Called on the event loop, so it only raises a flag and never takes the lock."""
        self._forget = True

    def _apply_forget(self) -> None:
        if self._forget:
            self._forget = False
            self._key = None
            self._refused = False
            self._password = ""

    def login(self) -> QrzSession:
        with self._lock:
            return self._login()

    def _login(self) -> QrzSession:
        self._apply_forget()
        if self._refused:
            raise QrzError(REFUSED)
        try:
            saved = load_login()
        except LoginUnavailable as exc:
            raise QrzError(str(exc)) from None
        if saved is None:
            raise QrzError(NO_LOGIN)
        username, self._password = saved
        reply = self._post({"username": username, "password": self._password,
                            "agent": self._agent})  # fmt: skip
        session = reply.session
        self._check_refused(session)
        if session.key is None:
            self._key = None
            reason = session.error or session.message or "no session from QRZ"
            raise QrzError(self._scrub(f"QRZ login failed: {reason}"))
        self._key = session.key
        return session

    def lookup(self, callsign: str) -> tuple[QrzRecord, str | None]:
        """The record and a notice to show with it (e.g. limited non-subscriber data)."""
        call = callsign.strip().upper()
        if not call:
            raise QrzError("Type a callsign first.")
        with self._lock:
            self._apply_forget()
            if self._refused:
                raise QrzError(REFUSED)
            if self._key is None:
                self._login()
            reply = self._post({"s": self._key or "", "callsign": call})
            self._check_refused(reply.session)
            if reply.session.key is None:  # the session ended: log in once, try once more
                self._login()
                reply = self._post({"s": self._key or "", "callsign": call})
                self._check_refused(reply.session)
            self._key = reply.session.key
            session = reply.session
            if session.error and session.error.lower().startswith("not found"):
                raise QrzError(f"{NOT_FOUND} {call}.")
            if session.error or reply.record is None:
                reason = session.error or session.message or f"{NOT_FOUND} {call}."
                raise QrzError(self._scrub(reason))
            if (session.sub_exp or "").strip().lower() == "non-subscriber":
                return reply.record, NON_SUBSCRIBER
            return reply.record, self._scrub(session.message) if session.message else None
