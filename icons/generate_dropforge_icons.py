from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ICON_DIR = Path(__file__).parent
SIZE = 512
ICON_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def color_gradient(start: tuple[int, int, int], end: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE))
    pixels = image.load()
    for y in range(SIZE):
        t = y / (SIZE - 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(start, end))
        for x in range(SIZE):
            pixels[x, y] = (*color, 255)
    return image


def make_icon(accent_top: tuple[int, int, int], accent_bottom: tuple[int, int, int], spark: tuple[int, int, int]) -> Image.Image:
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    tile_mask = Image.new("L", (SIZE, SIZE), 0)
    mask_draw = ImageDraw.Draw(tile_mask)
    mask_draw.rounded_rectangle((18, 18, SIZE - 18, SIZE - 18), radius=116, fill=255)

    tile = color_gradient((42, 31, 62), (14, 17, 27))
    canvas.paste(tile, (0, 0), tile_mask)

    tile_draw = ImageDraw.Draw(canvas)
    tile_draw.rounded_rectangle(
        (20, 20, SIZE - 20, SIZE - 20),
        radius=116,
        outline=(255, 255, 255, 30),
        width=5,
    )

    drop_points = [
        (256, 74), (307, 137), (350, 190), (375, 231), (391, 274), (389, 310),
        (373, 344), (347, 372), (314, 393), (284, 405), (256, 411), (228, 405),
        (198, 393), (165, 372), (139, 344), (123, 310), (121, 274), (137, 231),
        (162, 190), (205, 137),
    ]
    drop_mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(drop_mask).polygon(drop_points, fill=255)
    shadow_mask = drop_mask.filter(ImageFilter.GaussianBlur(20))
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 105))
    canvas.alpha_composite(Image.composite(shadow, Image.new("RGBA", (SIZE, SIZE)), shadow_mask))
    canvas.paste(color_gradient(accent_top, accent_bottom), (0, 0), drop_mask)

    draw = ImageDraw.Draw(canvas)
    # The dark silhouette reads as a small forge anvil inside the reward drop.
    anvil = [
        (163, 268), (349, 268), (327, 296), (294, 314), (285, 321),
        (285, 345), (337, 345), (358, 372), (154, 372), (175, 345),
        (227, 345), (227, 321), (218, 314), (185, 296),
    ]
    draw.polygon(anvil, fill=(23, 18, 33, 255))
    draw.line((179, 275, 333, 275), fill=(*spark, 255), width=10)

    # A four-point spark gives the mark a distinct silhouette at tray-icon sizes.
    draw.polygon(
        [(377, 91), (393, 127), (429, 143), (393, 159), (377, 195), (361, 159), (325, 143), (361, 127)],
        fill=(*spark, 255),
    )
    draw.ellipse((92, 211, 111, 230), fill=(255, 255, 255, 175))
    return canvas.resize((256, 256), Image.Resampling.LANCZOS)


def save_icon(filename: str, top: tuple[int, int, int], bottom: tuple[int, int, int], spark: tuple[int, int, int]) -> Image.Image:
    image = make_icon(top, bottom, spark)
    image.save(ICON_DIR / filename, format="ICO", sizes=ICON_SIZES)
    return image


def main() -> None:
    primary = save_icon("dropforge.ico", (204, 111, 255), (111, 76, 255), (116, 239, 220))
    save_icon("dropforge-active.ico", (95, 236, 185), (28, 165, 145), (231, 255, 170))
    save_icon("dropforge-idle.ico", (145, 158, 190), (76, 88, 125), (188, 207, 255))
    save_icon("dropforge-error.ico", (255, 113, 142), (196, 51, 91), (255, 220, 226))
    save_icon("dropforge-maint.ico", (255, 203, 103), (219, 123, 53), (255, 242, 194))
    primary.save(ICON_DIR / "dropforge-mark.png")


if __name__ == "__main__":
    main()
