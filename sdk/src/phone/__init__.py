import json
import logging
import os
from contextlib import contextmanager

from websockets.sync.client import connect

log = logging.getLogger("phone")
DEFAULT_URL = os.environ.get("PHONE_CONTROLLER_URL", "ws://localhost:8765")


class PhoneError(Exception):
    pass


class Session:
    def __init__(self, ws, session_id):
        self._ws = ws
        self.id = session_id
        self._next_id = 0

    def call(self, action, **args):
        self._next_id += 1
        self._ws.send(
            json.dumps(
                {"type": "call", "id": self._next_id, "action": action, "args": args}
            )
        )
        reply = json.loads(self._ws.recv())
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

    def tap_element(self, timeout=10, **selector):
        return self.call("tap_element", selector=selector, timeout=timeout)


@contextmanager
def session(holder, url=DEFAULT_URL):
    with connect(url) as ws:
        ws.send(json.dumps({"type": "open", "holder": holder}))
        while True:
            msg = json.loads(ws.recv())
            if msg["type"] == "granted":
                break
            if msg["type"] == "error":
                raise PhoneError(msg["error"])
            log.info("phone busy, position %d in queue", msg["position"])
        yield Session(ws, msg["session"])
