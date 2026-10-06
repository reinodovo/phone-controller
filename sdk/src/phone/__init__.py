import importlib.metadata
import json
import logging
import os
from contextlib import contextmanager

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

log = logging.getLogger("phone")
DEFAULT_URL = os.environ.get("PHONE_CONTROLLER_URL", "ws://localhost:8765")
VERSION = importlib.metadata.version("phone-sdk")


def series(version):
    if not version:
        return None
    major, minor = version.split(".")[:2]
    return f"0.{minor}" if major == "0" else major


class PhoneError(Exception):
    pass


class Session:
    def __init__(self, ws, session_id, url):
        self._ws = ws
        self.id = session_id
        self.url = url
        self._next_id = 0

    def call(self, action, **args):
        self._next_id += 1
        try:
            self._ws.send(
                json.dumps(
                    {
                        "type": "call",
                        "id": self._next_id,
                        "action": action,
                        "args": args,
                    }
                )
            )
            reply = json.loads(self._ws.recv())
        except ConnectionClosed as e:
            reason = e.rcvd.reason if e.rcvd and e.rcvd.reason else "connection lost"
            raise PhoneError(f"{action}: session closed ({reason})") from e
        if not reply["ok"]:
            raise PhoneError(f"{action}: {reply['error']}")
        return reply.get("value")

    def unlock(self):
        return self.call("unlock")

    def lock(self):
        return self.call("lock")

    def home(self):
        return self.call("home")

    def tap(self, x, y):
        return self.call("tap", x=x, y=y)

    def type(self, text):
        return self.call("type", text=text)

    def open_app(self, package, activity=None):
        return self.call("open_app", package=package, activity=activity)

    def close_app(self, package):
        return self.call("close_app", package=package)

    def back(self):
        return self.call("back")

    def swipe(self, x1, y1, x2, y2, duration=0.3):
        return self.call("swipe", x1=x1, y1=y1, x2=x2, y2=y2, duration=duration)

    def dump(self):
        return self.call("dump")

    def current_app(self):
        return self.call("current_app")

    def is_playing(self):
        return self.call("is_playing")

    def wait_for(self, selectors, timeout=15):
        return self.call("wait_for", selectors=selectors, timeout=timeout)

    def wait_gone(self, timeout=15, **selector):
        return self.call("wait_gone", selector=selector, timeout=timeout)

    def tap_element(self, timeout=10, **selector):
        return self.call("tap_element", selector=selector, timeout=timeout)


@contextmanager
def session(holder, url=DEFAULT_URL, debug=False):
    with connect(url) as ws:
        ws.send(
            json.dumps(
                {"type": "open", "holder": holder, "debug": debug, "version": VERSION}
            )
        )
        while True:
            msg = json.loads(ws.recv())
            if msg["type"] == "error":
                raise PhoneError(msg["error"])
            controller = msg.get("version")
            if not controller or series(controller) != series(VERSION):
                raise PhoneError(
                    f"controller {controller or 'without a version'} is incompatible with SDK {VERSION}"
                )
            if msg["type"] == "granted":
                break
            log.info("phone busy, position %d in queue", msg["position"])
        yield Session(ws, msg["session"], msg["url"])
