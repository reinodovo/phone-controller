import re
import xml.etree.ElementTree as ET

import uiautomator2

from controller.device import device

BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_u2 = None


def u2():
    global _u2
    if _u2 is None:
        _u2 = uiautomator2.connect(device().serial)
    return _u2


def dump_xml():
    global _u2
    try:
        return u2().dump_hierarchy()
    except Exception:  # noqa: BLE001
        _u2 = None
        return u2().dump_hierarchy()


def nodes(xml):
    for node in ET.fromstring(xml).iter("node"):
        m = BOUNDS.match(node.get("bounds", ""))
        if not m:
            continue
        yield {
            "text": node.get("text", ""),
            "id": node.get("resource-id", ""),
            "desc": node.get("content-desc", ""),
            "class": node.get("class", ""),
            "package": node.get("package", ""),
            "clickable": node.get("clickable") == "true",
            "bounds": [int(v) for v in m.groups()],
        }


def elements(xml):
    return [
        n
        for n in nodes(xml)
        if n["bounds"][2] > n["bounds"][0]
        and n["bounds"][3] > n["bounds"][1]
        and (n["text"] or n["desc"] or n["id"] or n["clickable"])
    ]


def screen_size(xml):
    width = height = 0
    for n in nodes(xml):
        width, height = max(width, n["bounds"][2]), max(height, n["bounds"][3])
    return width, height


def current_app():
    app = device().app_current()
    return {"package": app.package, "activity": app.activity, "pid": app.pid}


def snapshot():
    xml = dump_xml()
    return xml, {**current_app(), "elements": elements(xml)}


def matches(element, selector):
    for key, want in selector.items():
        if key == "id":
            ok = element["id"] == want or element["id"].endswith(f":id/{want}")
        elif key in ("text", "desc", "class", "package", "clickable"):
            ok = element[key] == want
        elif key.endswith("_contains"):
            ok = want in element[key.removesuffix("_contains")]
        elif key.endswith("_starts"):
            ok = element[key.removesuffix("_starts")].startswith(want)
        elif key.endswith("_matches"):
            ok = re.search(want, element[key.removesuffix("_matches")]) is not None
        else:
            raise ValueError(f"unknown selector key {key!r}")
        if not ok:
            return False
    return True


def find(screen, selector):
    if "activity" in selector or "app" in selector:
        app_ok = selector.get("activity") in (
            None,
            screen["activity"],
        ) and selector.get("app") in (None, screen["package"])
        rest = {k: v for k, v in selector.items() if k not in ("activity", "app")}
        if not app_ok:
            return None
        if not rest:
            return {}
        selector = rest
    return next((e for e in screen["elements"] if matches(e, selector)), None)


def center(element):
    x1, y1, x2, y2 = element["bounds"]
    return (x1 + x2) // 2, (y1 + y2) // 2
