import asyncio
import contextlib
import importlib.metadata
import json
import logging
import os
import sys
import time
import uuid

import structlog
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from controller import actions, layout, screen, storage, viewer
from controller.actions import ACTIONS, foreground_package, launcher_package
from controller.device import capture_screen

VERSION = importlib.metadata.version("phone-controller")
HOSTS = os.environ.get("PHONE_CONTROLLER_HOST", "localhost").split(",")
PORT = int(os.environ.get("PHONE_CONTROLLER_PORT", "8765"))
PUBLIC_URL = os.environ.get("PHONE_CONTROLLER_PUBLIC_URL", f"http://localhost:{PORT}")
IDLE_TIMEOUT = float(os.environ.get("PHONE_CONTROLLER_IDLE_TIMEOUT", "60"))
PAYMENT_CHECK = os.environ.get("PHONE_CONTROLLER_PAYMENT_CHECK", "").lower() in {
    "1",
    "true",
    "yes",
}

log = structlog.get_logger("phone-controller")
phone_lock = asyncio.Lock()
waiting = 0
RECORD_BEFORE = {"tap", "tap_element", "swipe"}
READ_ONLY = {"dump", "wait_for", "wait_gone", "current_app", "is_playing"}
POLLING = {"wait_for", "wait_gone"}


def series(version):
    if not version:
        return None
    major, minor = version.split(".")[:2]
    return f"0.{minor}" if major == "0" else major


async def handle(ws):
    global waiting
    msg = json.loads(await ws.recv())
    holder = msg.get("holder", "?")
    debug = bool(msg.get("debug"))
    sdk_version = msg.get("version")
    if series(sdk_version) != series(VERSION):
        error = f"SDK {sdk_version or 'without a version'} is incompatible with controller {VERSION}, use a {series(VERSION)}.x SDK"
        log.warning("rejected session", holder=holder, sdk=sdk_version)
        await ws.send(json.dumps({"type": "error", "error": error}))
        return
    asked_at = time.monotonic()
    waiting += 1
    if phone_lock.locked():
        await ws.send(
            json.dumps({"type": "waiting", "position": waiting, "version": VERSION})
        )
    try:
        await phone_lock.acquire()
    finally:
        waiting -= 1
    session_id = str(uuid.uuid4())
    granted_at = time.monotonic()
    waited = round(granted_at - asked_at, 2)
    record = storage.SessionRecord(session_id, holder, waited, debug)
    structlog.contextvars.bind_contextvars(session=session_id, holder=holder)
    log.info("session granted", waited=waited, debug=debug)
    opened, closed_reason = set(), None
    try:
        unlocked = {}
        await run_action(record, {"action": "unlock"}, unlocked, source="internal")
        if not unlocked["ok"]:
            await ws.send(
                json.dumps(
                    {"type": "error", "error": f"unlock failed: {unlocked['error']}"}
                )
            )
            return
        await run_action(record, {"action": "home"}, {}, source="internal")
        url = f"{PUBLIC_URL}/sessions/{session_id}"
        await ws.send(
            json.dumps(
                {
                    "type": "granted",
                    "session": session_id,
                    "url": url,
                    "version": VERSION,
                }
            )
        )
        while True:
            try:
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=None if debug else IDLE_TIMEOUT
                )
            except TimeoutError:
                closed_reason = f"idle for {IDLE_TIMEOUT:g}s"
                log.info("closing idle session", idle=IDLE_TIMEOUT)
                await ws.close(4000, closed_reason)
                break
            except ConnectionClosed:
                break
            call = json.loads(raw)
            reply = {"type": "result", "id": call["id"]}
            await run_action(record, call, reply)
            if call["action"] == "open_app" and reply["ok"]:
                opened.add(call["args"]["package"])
            await ws.send(json.dumps(reply))
    finally:
        await clean_up(record, opened)
        phone_lock.release()
        duration = round(time.monotonic() - granted_at, 2)
        record.close(duration, closed_reason)
        log.info(
            "session closed",
            actions=record.meta["actions"],
            duration=duration,
            reason=closed_reason,
        )
        structlog.contextvars.clear_contextvars()


async def clean_up(record, opened):
    internal = Internal(record)
    try:
        front = await asyncio.to_thread(
            internal.call, "foreground_package", foreground_package
        )
        launcher = await asyncio.to_thread(
            internal.call, "launcher_package", launcher_package
        )
        if front not in {launcher, "com.android.systemui"}:
            opened.add(front)
    except Exception as e:  # noqa: BLE001
        log.warning("could not read the app in front", error=str(e))
    for package in sorted(opened):
        await run_action(
            record,
            {"action": "close_app", "args": {"package": package}},
            {},
            source="internal",
        )
    await run_action(record, {"action": "home"}, {}, source="internal")
    await run_action(record, {"action": "lock"}, {}, source="internal")


class Internal:
    def __init__(self, record, parent=None):
        self.record = record
        self.parent = parent

    def step(self, name, args=None):
        n = self.record.next_step()
        step = {
            "n": n,
            "source": "internal",
            "parent": self.parent,
            "action": name,
            "args": args or {},
            "started_at": storage.now(),
        }
        return n, step

    def finish(self, step, started, error=None):
        step.update(ok=error is None, took=round(time.monotonic() - started, 2))
        if error is not None:
            step["error"] = str(error)
        self.record.add_step(step)

    def snapshot(self):
        n, step = self.step("dump")
        started = time.monotonic()
        try:
            xml, current = screen.snapshot()
            step.update(save_dump(self.record, n, "dump", xml, screenshot=False))
        except Exception as e:
            self.finish(step, started, e)
            raise
        self.finish(step, started)
        return xml, current

    def call(self, name, fn, *args):
        _, step = self.step(name)
        started = time.monotonic()
        try:
            value = fn(*args)
        except Exception as e:
            self.finish(step, started, e)
            raise
        step["value"] = value
        self.finish(step, started)
        return value


async def run_action(record, call, reply, source="user"):
    name, args = call["action"], call.get("args", {})
    n = record.next_step(user=source == "user")
    step = {
        "n": n,
        "source": source,
        "action": name,
        "args": args,
        "started_at": storage.now(),
    }
    internal = Internal(record, parent=n)
    started = time.monotonic()
    try:
        if name == "dump":
            xml, value = await asyncio.to_thread(screen.snapshot)
            step.update(await asyncio.to_thread(save_dump, record, n, name, xml))
        else:
            xml, marks, value = None, {}, None
            if name == "tap_element":
                xml, element = await asyncio.to_thread(
                    actions.locate,
                    args["selector"],
                    args.get("timeout", 10),
                    snapshot=internal.snapshot,
                )
                x, y = screen.center(element)
                action, action_args, value = actions.tap, {"x": x, "y": y}, element
                marks = {"box": element["bounds"], "point": (x, y)}
            else:
                action, action_args = ACTIONS.get(name), args
                if action is None:
                    raise ValueError(f"unknown action {name!r}")
                if name in POLLING:
                    action_args = {**args, "snapshot": internal.snapshot}
                elif name == "tap":
                    marks = {"point": (int(args["x"]), int(args["y"]))}
                elif name == "swipe":
                    marks = {
                        "line": ((args["x1"], args["y1"]), (args["x2"], args["y2"]))
                    }
            if name in RECORD_BEFORE:
                step["image"], step["image_source"] = await asyncio.to_thread(
                    record_before, record, n, name, xml, marks
                )
            result = await asyncio.to_thread(action, **action_args)
            value = value if name == "tap_element" else result
        if (
            PAYMENT_CHECK
            and name not in READ_ONLY
            and await asyncio.to_thread(internal.call, "payment_check", payment_screen)
        ):
            await asyncio.to_thread(internal.call, "back", actions.back)
            raise RuntimeError("Play Store payment screen appeared, pressed back")
        reply.update(ok=True, value=value)
        step.update(ok=True)
        log.info("action ok", action=name, took=round(time.monotonic() - started, 2))
    except Exception as e:  # noqa: BLE001
        reply.update(ok=False, error=str(e))
        step.update(ok=False, error=str(e))
        log.warning("action failed", action=name, error=str(e))
    step["took"] = round(time.monotonic() - started, 2)
    await asyncio.to_thread(record.add_step, step)


def save_dump(record, n, name, xml, screenshot=True):
    background = layout.screenshot_image(capture_screen()) if screenshot else None
    return {
        "dump": record.save_text(n, name, xml, "xml"),
        "image": record.save_image(n, name, layout.draw_layout(xml, background)),
        "image_source": "layout" if background is None else "overlay",
    }


def record_before(record, n, name, xml, marks):
    image, source = layout.screenshot_image(capture_screen()), "screenshot"
    if image is None:
        image, source = layout.draw_layout(xml or screen.dump_xml()), "layout"
    return record.save_image(n, name, layout.mark(image, **marks)), source


def payment_screen():
    app = screen.current_app()
    return app["package"] == "com.android.vending" and ".billing." in app["activity"]


def setup_logging():
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    log_format = os.environ.get(
        "LOG_FORMAT", "console" if sys.stderr.isatty() else "json"
    )
    renderer = (
        structlog.dev.ConsoleRenderer()
        if log_format == "console"
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=shared + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )
    logging.basicConfig(handlers=[handler], level=logging.INFO)


async def main():
    setup_logging()
    async with contextlib.AsyncExitStack() as stack:
        for host in HOSTS:
            await stack.enter_async_context(
                serve(handle, host, PORT, process_request=viewer.process_request)
            )
        log.info("listening", hosts=HOSTS, port=PORT, version=VERSION)
        await prune_forever()


async def prune_forever():
    while True:
        try:
            for session_id in await asyncio.to_thread(storage.prune_sessions):
                log.info("deleted old session", session=session_id)
        except Exception as e:  # noqa: BLE001
            log.warning("pruning old sessions failed", error=str(e))
        await asyncio.sleep(3600)


asyncio.run(main())
