from PIL import Image, ImageDraw, ImageFont

FOREST = (44, 74, 59)      # var(--forest)
SIGNAL = (224, 163, 57)    # var(--signal)
PAPER  = (246, 243, 236)   # var(--paper)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"

def make_icon(size, path, corner_radius_ratio=0.22):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = int(size * corner_radius_ratio)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=FOREST)

    # Letter "C"
    font_size = int(size * 0.58)
    font = ImageFont.truetype(FONT_PATH, font_size)
    text = "C"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) / 2 - bbox[0]
    ty = (size - th) / 2 - bbox[1]
    draw.text((tx, ty), text, font=font, fill=PAPER)

    # Signal-colored accent dot, bottom right of the letter
    dot_r = size * 0.045
    dot_cx = size * 0.68
    dot_cy = size * 0.72
    draw.ellipse(
        [dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r],
        fill=SIGNAL,
    )

    img.save(path)
    print(f"Saved {path} ({size}x{size})")


if __name__ == "__main__":
    make_icon(192, "icons/icon-192.png")
    make_icon(512, "icons/icon-512.png")
    make_icon(180, "icons/apple-touch-icon.png", corner_radius_ratio=0.0)  # iOS adds its own mask
    make_icon(32, "icons/favicon-32.png")
