import asyncio
import contextlib
import json
import logging
import os
import sys
import time
import uuid

import structlog
from websockets.asyncio.server import serve

from controller import actions, layout, screen, storage, viewer
from controller.actions import ACTIONS, foreground_package, launcher_package
from controller.device import capture_screen

HOSTS = os.environ.get("PHONE_CONTROLLER_HOST", "localhost").split(",")
PORT = int(os.environ.get("PHONE_CONTROLLER_PORT", "8765"))

log = structlog.get_logger("phone-controller")
phone_lock = asyncio.Lock()
waiting = 0
RECORD_BEFORE = {"tap", "tap_element", "swipe"}
READ_ONLY = {"dump", "wait_for", "current_app", "is_playing"}


async def handle(ws):
    global waiting
    msg = json.loads(await ws.recv())
    holder = msg.get("holder", "?")
    asked_at = time.monotonic()
    waiting += 1
    if phone_lock.locked():
        await ws.send(json.dumps({"type": "waiting", "position": waiting}))
    try:
        await phone_lock.acquire()
    finally:
        waiting -= 1
    session_id = str(uuid.uuid4())
    granted_at = time.monotonic()
    waited = round(granted_at - asked_at, 2)
    record = storage.SessionRecord(session_id, holder, waited)
    structlog.contextvars.bind_contextvars(session=session_id, holder=holder)
    log.info("session granted", waited=waited)
    opened = set()
    try:
        unlocked = {}
        await run_action(record, {"action": "unlock"}, unlocked)
        if not unlocked["ok"]:
            await ws.send(
                json.dumps(
                    {"type": "error", "error": f"unlock failed: {unlocked['error']}"}
                )
            )
            return
        await run_action(record, {"action": "home"}, {})
        await ws.send(json.dumps({"type": "granted", "session": session_id}))
        async for raw in ws:
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
        record.close(duration)
        log.info("session closed", actions=record.meta["actions"], duration=duration)
        structlog.contextvars.clear_contextvars()


async def clean_up(record, opened):
    try:
        front = await asyncio.to_thread(foreground_package)
        if front not in {
            await asyncio.to_thread(launcher_package),
            "com.android.systemui",
        }:
            opened.add(front)
    except Exception as e:  # noqa: BLE001
        log.warning("could not read the app in front", error=str(e))
    for package in sorted(opened):
        await run_action(
            record, {"action": "close_app", "args": {"package": package}}, {}
        )
    await run_action(record, {"action": "home"}, {})
    await run_action(record, {"action": "lock"}, {})


async def run_action(record, call, reply):
    name, args = call["action"], call.get("args", {})
    n = record.next_step()
    step = {"n": n, "action": name, "args": args, "started_at": storage.now()}
    started = time.monotonic()
    try:
        if name == "dump":
            xml, value = await asyncio.to_thread(screen.snapshot)
            step["dump"] = await asyncio.to_thread(
                record.save_text, n, name, xml, "xml"
            )
            background = layout.screenshot_image(
                await asyncio.to_thread(capture_screen)
            )
            image = await asyncio.to_thread(layout.draw_layout, xml, background)
            step["image"] = await asyncio.to_thread(record.save_image, n, name, image)
            step["image_source"] = "layout" if background is None else "overlay"
        else:
            xml, marks, value = None, {}, None
            if name == "tap_element":
                xml, element = await asyncio.to_thread(
                    actions.locate, args["selector"], args.get("timeout", 10)
                )
                x, y = screen.center(element)
                action, action_args, value = actions.tap, {"x": x, "y": y}, element
                marks = {"box": element["bounds"], "point": (x, y)}
            else:
                action, action_args = ACTIONS.get(name), args
                if action is None:
                    raise ValueError(f"unknown action {name!r}")
                if name == "tap":
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
        if name not in READ_ONLY and await asyncio.to_thread(payment_screen):
            await asyncio.to_thread(actions.back)
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
        log.info("listening", hosts=HOSTS, port=PORT)
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
