import time

from controller import screen
from controller.device import adb_shell, device


def unlock():
    adb_shell("input", "keyevent", "KEYCODE_WAKEUP")
    adb_shell("wm", "dismiss-keyguard")


def home():
    adb_shell("input", "keyevent", "KEYCODE_HOME")


def foreground_package():
    return device().app_current().package


def launcher_package():
    out = adb_shell(
        "cmd",
        "package",
        "resolve-activity",
        "--brief",
        "-c",
        "android.intent.category.HOME",
    )
    return out.strip().splitlines()[-1].split("/")[0]


def back():
    adb_shell("input", "keyevent", "KEYCODE_BACK")


def swipe(x1, y1, x2, y2, duration=0.3):
    adb_shell(
        "input",
        "swipe",
        *(str(int(v)) for v in (x1, y1, x2, y2)),
        str(int(duration * 1000)),
    )


def current_app():
    return screen.current_app()


def is_playing():
    pid = device().app_current().pid
    audio = adb_shell("dumpsys", "audio")
    return any(
        f"/{pid} " in line and "state:started" in line and "USAGE_MEDIA" in line
        for line in audio.splitlines()
    )


def wait_for(selectors, timeout=15, interval=0.5):
    deadline = time.monotonic() + timeout
    while True:
        _, current = screen.snapshot()
        for name, selector in selectors.items():
            element = screen.find(current, selector)
            if element is not None:
                return {"matched": name, "element": element or None}
        if time.monotonic() >= deadline:
            return {"matched": None, "element": None}
        time.sleep(interval)


def locate(selector, timeout=10, interval=0.5):
    deadline = time.monotonic() + timeout
    while True:
        xml, current = screen.snapshot()
        element = screen.find(current, selector)
        if element:
            return xml, element
        if time.monotonic() >= deadline:
            raise LookupError(f"no element matching {selector} within {timeout}s")
        time.sleep(interval)


def lock():
    adb_shell("input", "keyevent", "KEYCODE_SLEEP")


def tap(x, y):
    adb_shell("input", "tap", str(int(x)), str(int(y)))


def type_text(text):
    adb_shell("input", "text", text.replace(" ", "%s"))


def launcher_activity(package):
    out = adb_shell(
        "cmd",
        "package",
        "resolve-activity",
        "--brief",
        "-c",
        "android.intent.category.LAUNCHER",
        package,
    )
    component = out.strip().splitlines()[-1]
    if "/" not in component:
        raise ValueError(f"no launcher activity for {package!r}")
    return component


def open_app(package, activity=None):
    component = f"{package}/{activity}" if activity else launcher_activity(package)
    out = adb_shell("am", "start", "-W", "-n", component)
    if "Error" in out:
        raise RuntimeError(out.strip())


def close_app(package):
    adb_shell("am", "force-stop", package)


ACTIONS = {
    "unlock": unlock,
    "lock": lock,
    "home": home,
    "back": back,
    "swipe": swipe,
    "current_app": current_app,
    "is_playing": is_playing,
    "wait_for": wait_for,
    "tap": tap,
    "type": type_text,
    "open_app": open_app,
    "close_app": close_app,
}
