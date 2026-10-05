import os

from adbutils import adb

ADB_TIMEOUT = 30
SERIAL = os.environ.get("PHONE_SERIAL")


def device():
    if SERIAL:
        return adb.device(SERIAL)
    devices = [d for d in adb.device_list() if not d.serial.startswith("emulator-")]
    if not devices:
        raise RuntimeError("no phone connected to the adb server")
    return devices[0]


def adb_shell(*args):
    result = device().shell2(list(args), timeout=ADB_TIMEOUT)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {result.output.strip()}")
    return result.output


def capture_screen():
    return device().shell("screencap -p", encoding=None, timeout=ADB_TIMEOUT)
