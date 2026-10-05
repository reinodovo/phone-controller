import io

from PIL import Image, ImageDraw, ImageEnhance

from controller import screen

COLORS = {"clickable": "lime", "text": "deepskyblue", "other": "gray"}
MARK = "red"


def draw_layout(xml, background=None):
    if background is None:
        image = Image.new("RGB", screen.screen_size(xml) or (720, 1480), (18, 18, 18))
    else:
        image = ImageEnhance.Brightness(background).enhance(0.55)
    draw = ImageDraw.Draw(image)
    used = set()
    for e in screen.elements(xml):
        kind = (
            "clickable"
            if e["clickable"]
            else "text"
            if e["text"] or e["desc"]
            else "other"
        )
        draw.rectangle(
            e["bounds"], outline=COLORS[kind], width=1 if kind == "other" else 3
        )
        name = e["id"].split("/")[-1] or e["class"].split(".")[-1]
        label = " ".join(
            filter(
                None,
                [name, repr(e["text"] or e["desc"]) if e["text"] or e["desc"] else ""],
            )
        )
        x, y = e["bounds"][0] + 4, e["bounds"][1] + 4
        while (x, y) in used:
            y += 14
        used.add((x, y))
        draw.text((x, y), label, fill=COLORS[kind], stroke_width=2, stroke_fill="black")
    footer = "UI dump over screenshot" if background else "layout drawn from UI dump"
    draw.text(
        (8, image.height - 20),
        footer,
        fill="white",
        stroke_width=2,
        stroke_fill="black",
    )
    return image


def screenshot_image(png):
    if not png:
        return None
    try:
        image = Image.open(io.BytesIO(png)).convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    if image.convert("L").getextrema() == (0, 0):
        return None
    return image


def mark(image, point=None, box=None, line=None):
    draw = ImageDraw.Draw(image)
    if box:
        draw.rectangle(box, outline=MARK, width=4)
    if point:
        x, y = point
        draw.ellipse((x - 25, y - 25, x + 25, y + 25), outline=MARK, width=4)
        draw.line((x - 40, y, x + 40, y), fill=MARK, width=2)
        draw.line((x, y - 40, x, y + 40), fill=MARK, width=2)
    if line:
        (x1, y1), (x2, y2) = line
        draw.line((x1, y1, x2, y2), fill=MARK, width=6)
        draw.ellipse((x1 - 15, y1 - 15, x1 + 15, y1 + 15), outline=MARK, width=4)
        draw.ellipse((x2 - 8, y2 - 8, x2 + 8, y2 + 8), fill=MARK)
    return image
