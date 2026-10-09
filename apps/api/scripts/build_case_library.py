"""Create original, project-owned illustrations for the stored artwork collection."""

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / "apps/web/public/case-library"


def city():
    image = Image.new("RGB", (768, 960))
    draw = ImageDraw.Draw(image)
    for y in range(960):
        t = y / 960
        draw.line((0, y, 768, y), fill=(int(7 + 10 * t), int(17 + 35 * t), int(43 + 38 * t)))
    randomizer = random.Random(422)
    for _ in range(210):
        x, y = randomizer.randrange(768), randomizer.randrange(520)
        r = randomizer.choice([1, 1, 2])
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(147, 179, 221))
    draw.ellipse((458, 92, 624, 258), fill=(242, 209, 151))
    draw.ellipse((473, 90, 625, 246), fill=(236, 190, 124))
    for layer, color in enumerate([(29, 61, 91), (19, 44, 73), (12, 31, 59)]):
        for x in range(-30, 800, 62):
            top = 390 + layer * 96 + randomizer.randrange(140)
            draw.rectangle((x, top, x + 55, 850), fill=color)
            draw.polygon([(x - 4, top), (x + 27, top - 25), (x + 59, top)], fill=color)
            for wy in range(top + 18, 810, 30):
                for wx in range(x + 9, x + 45, 15):
                    if randomizer.random() > 0.27:
                        draw.rectangle(
                            (wx, wy, wx + 5, wy + 10),
                            fill=randomizer.choice(
                                [(200, 154, 93), (87, 146, 169), (220, 189, 120)]
                            ),
                        )
    draw.rounded_rectangle((242, 355, 522, 959), radius=140, fill=(177, 158, 125))
    draw.rounded_rectangle((274, 392, 490, 1000), radius=108, fill=(7, 24, 47))
    for y in range(460, 960, 32):
        draw.line((246, y, 270, y), fill=(115, 111, 103), width=2)
        draw.line((494, y, 519, y), fill=(115, 111, 103), width=2)
    for x in range(245, 522, 28):
        angle = (x - 245) / 277 * math.pi
        draw.line(
            (
                x,
                355 + int(82 * (1 - math.sin(angle))),
                x + 8,
                382 + int(77 * (1 - math.sin(angle))),
            ),
            fill=(128, 116, 96),
            width=2,
        )
    draw.ellipse((340, 628, 427, 715), fill=(246, 206, 129))
    for i in range(14):
        y = 739 + i * 16
        width = 18 + i * 9
        draw.line((384 - width, y, 384 + width, y), fill=(65 + i * 7, 107 + i * 3, 123), width=3)
    draw.polygon([(0, 836), (228, 750), (273, 797), (236, 960), (0, 960)], fill=(14, 32, 50))
    draw.polygon([(768, 836), (545, 750), (492, 797), (529, 960), (768, 960)], fill=(14, 32, 50))
    for x in range(22, 232, 30):
        draw.line((x, 858, x - 25, 960), fill=(64, 90, 105), width=2)
    for x in range(544, 770, 30):
        draw.line((x, 858, x + 25, 960), fill=(64, 90, 105), width=2)
    draw.line((35, 919, 160, 919), fill=(228, 188, 122), width=2)
    draw.text((35, 933), "NOCTURNE / 01", fill=(182, 199, 211))
    return image


def garden():
    image = Image.new("RGB", (768, 960), (232, 222, 202))
    draw = ImageDraw.Draw(image)
    draw.rectangle((32, 32, 736, 928), outline=(85, 109, 110), width=2)
    draw.ellipse((240, 90, 526, 376), fill=(192, 100, 79))
    rng = random.Random(103)
    for row in range(10):
        y = 365 + row * 55
        points = (
            [(0, y + 25)]
            + [(x, y + int(38 * math.sin(x / 115 + row * 0.7))) for x in range(0, 800, 8)]
            + [(768, 960), (0, 960)]
        )
        color = (int(49 + row * 6), int(96 + row * 4), int(92 + row * 3))
        draw.polygon(points, fill=color)
    for _ in range(65):
        x, y = rng.randrange(40, 725), rng.randrange(500, 920)
        draw.line((x, y, x + 6, y - 37), fill=(198, 207, 169), width=2)
        for side in [-1, 1]:
            draw.ellipse(
                (x + side * 12 - 8, y - 32, x + side * 12 + 8, y - 23), fill=(153, 178, 138)
            )
    draw.rectangle((45, 866, 276, 910), fill=(232, 222, 202))
    draw.text((59, 879), "TIDAL GARDEN / 02", fill=(50, 80, 80))
    return image


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    nocturne = city()
    garden_image = garden()
    nocturne.save(ASSETS / "nocturne-original.png")
    nocturne.save(ASSETS / "nocturne-republished.png")
    garden_image.save(ASSETS / "garden-original.png")
    # This is a recorded crop, not an AI-generation claim.
    garden_image.crop((50, 100, 718, 915)).save(ASSETS / "garden-cropped.png")


if __name__ == "__main__":
    main()
