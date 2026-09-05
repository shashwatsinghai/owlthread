"""Generate modern Cyber-Owl extension vector SVG & crisp icon PNG files."""

import os
from pathlib import Path
from PIL import Image, ImageDraw

icons_dir = Path(r"c:\Users\AnshK\Downloads\OwlTherad\extension\icons")
icons_dir.mkdir(parents=True, exist_ok=True)

# 1. Save Modern Vector SVG
svg_code = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#090d16" />
      <stop offset="50%" stop-color="#1e1b4b" />
      <stop offset="100%" stop-color="#31104b" />
    </linearGradient>
    <linearGradient id="ringGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#6366f1" />
      <stop offset="50%" stop-color="#8b5cf6" />
      <stop offset="100%" stop-color="#38bdf8" />
    </linearGradient>
    <linearGradient id="eyeGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8" />
      <stop offset="100%" stop-color="#10b981" />
    </linearGradient>
    <linearGradient id="beakGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#fbbf24" />
      <stop offset="100%" stop-color="#f59e0b" />
    </linearGradient>
    <linearGradient id="featherGrad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#818cf8" stop-opacity="0.95" />
      <stop offset="100%" stop-color="#4f46e5" stop-opacity="0.6" />
    </linearGradient>
  </defs>

  <!-- Background Shield Disc -->
  <circle cx="64" cy="64" r="58" fill="url(#bgGrad)" stroke="url(#ringGrad)" stroke-width="4" />
  <circle cx="64" cy="64" r="50" fill="none" stroke="#4338ca" stroke-width="1.5" stroke-dasharray="4 3" opacity="0.6" />

  <!-- Owl Feather Ears / Crest -->
  <path d="M30 38 L48 48 L38 22 Z" fill="url(#featherGrad)" />
  <path d="M98 38 L80 48 L90 22 Z" fill="url(#featherGrad)" />

  <!-- Owl Head Visor -->
  <path d="M32 46 C44 40 56 46 64 50 C72 46 84 40 96 46 C100 60 98 76 92 90 C84 104 74 110 64 110 C54 110 44 104 36 90 C30 76 28 60 32 46 Z" 
        fill="#1e1b4b" stroke="#6366f1" stroke-width="2.5" />

  <!-- Angular Eyebrow Ridge -->
  <path d="M34 52 Q50 46 62 58 L64 60 L66 58 Q78 46 94 52" 
        fill="none" stroke="#818cf8" stroke-width="3.5" stroke-linecap="round" />

  <!-- Eye Sockets & Glowing Irises -->
  <circle cx="48" cy="68" r="14" fill="#090d16" stroke="#4f46e5" stroke-width="2" />
  <circle cx="48" cy="68" r="9" fill="url(#eyeGrad)" />
  <circle cx="48" cy="68" r="4.5" fill="#090d16" />
  <circle cx="46" cy="66" r="2" fill="#ffffff" opacity="0.9" />

  <circle cx="80" cy="68" r="14" fill="#090d16" stroke="#4f46e5" stroke-width="2" />
  <circle cx="80" cy="68" r="9" fill="url(#eyeGrad)" />
  <circle cx="80" cy="68" r="4.5" fill="#090d16" />
  <circle cx="78" cy="66" r="2" fill="#ffffff" opacity="0.9" />

  <!-- Geometric Golden Beak -->
  <polygon points="64,84 57,72 71,72" fill="url(#beakGrad)" />

  <!-- Chest Cyber Chevrons -->
  <path d="M52 92 L64 99 L76 92" fill="none" stroke="#6366f1" stroke-width="2" stroke-linecap="round" opacity="0.75" />
  <path d="M56 100 L64 105 L72 100" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" opacity="0.85" />
</svg>"""

(icons_dir / "owl_logo.svg").write_text(svg_code, encoding="utf-8")
print("Saved owl_logo.svg")

# 2. Render High-Quality Supersampled PNGs
def render_cyber_owl(size: int, filename: str):
    scale = 4
    canvas_size = size * scale
    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    center = canvas_size / 2
    r_outer = (canvas_size / 2) - (2 * scale)

    # Base shield disc: dark obsidian indigo (#090d16)
    draw.ellipse(
        [center - r_outer, center - r_outer, center + r_outer, center + r_outer],
        fill=(15, 23, 42, 255),
        outline=(99, 102, 241, 255),
        width=int(2.5 * scale)
    )

    # Inner cyber contour
    r_inner = r_outer * 0.88
    draw.ellipse(
        [center - r_inner, center - r_inner, center + r_inner, center + r_inner],
        outline=(67, 56, 202, 160),
        width=max(1, int(1.2 * scale))
    )

    # Owl Ears (sharp triangles)
    ear_top_y = canvas_size * 0.18
    ear_base_y = canvas_size * 0.38
    draw.polygon([
        (canvas_size * 0.24, ear_base_y),
        (canvas_size * 0.40, ear_base_y + scale * 2),
        (canvas_size * 0.30, ear_top_y)
    ], fill=(99, 102, 241, 240))
    draw.polygon([
        (canvas_size * 0.76, ear_base_y),
        (canvas_size * 0.60, ear_base_y + scale * 2),
        (canvas_size * 0.70, ear_top_y)
    ], fill=(99, 102, 241, 240))

    # Mask / Brow curve
    brow_y = canvas_size * 0.42
    draw.chord(
        [canvas_size * 0.22, canvas_size * 0.32, canvas_size * 0.78, canvas_size * 0.85],
        0, 180,
        fill=(30, 27, 75, 255),
        outline=(129, 140, 248, 220),
        width=int(1.8 * scale)
    )

    # Eyes
    eye_r = canvas_size * 0.13
    eye_y = canvas_size * 0.52
    left_x = canvas_size * 0.37
    right_x = canvas_size * 0.63

    # Eye Sockets (dark metallic)
    draw.ellipse([left_x - eye_r, eye_y - eye_r, left_x + eye_r, eye_y + eye_r], fill=(9, 13, 22, 255), outline=(79, 70, 229, 255), width=int(1.5 * scale))
    draw.ellipse([right_x - eye_r, eye_y - eye_r, right_x + eye_r, eye_y + eye_r], fill=(9, 13, 22, 255), outline=(79, 70, 229, 255), width=int(1.5 * scale))

    # Glowing Cyan Iris
    iris_r = eye_r * 0.68
    draw.ellipse([left_x - iris_r, eye_y - iris_r, left_x + iris_r, eye_y + iris_r], fill=(56, 189, 248, 255))
    draw.ellipse([right_x - iris_r, eye_y - iris_r, right_x + iris_r, eye_y + iris_r], fill=(56, 189, 248, 255))

    # Inner Pupils
    pupil_r = iris_r * 0.48
    draw.ellipse([left_x - pupil_r, eye_y - pupil_r, left_x + pupil_r, eye_y + pupil_r], fill=(9, 13, 22, 255))
    draw.ellipse([right_x - pupil_r, eye_y - pupil_r, right_x + pupil_r, eye_y + pupil_r], fill=(9, 13, 22, 255))

    # Eye Highlights
    hl_r = pupil_r * 0.45
    draw.ellipse([left_x - pupil_r * 0.4 - hl_r, eye_y - pupil_r * 0.4 - hl_r, left_x - pupil_r * 0.4 + hl_r, eye_y - pupil_r * 0.4 + hl_r], fill=(255, 255, 255, 240))
    draw.ellipse([right_x - pupil_r * 0.4 - hl_r, eye_y - pupil_r * 0.4 - hl_r, right_x - pupil_r * 0.4 + hl_r, eye_y - pupil_r * 0.4 + hl_r], fill=(255, 255, 255, 240))

    # Beak (sharp gold triangle)
    beak_w = canvas_size * 0.11
    beak_top_y = canvas_size * 0.58
    beak_tip_y = canvas_size * 0.72
    draw.polygon([
        (center - beak_w / 2, beak_top_y),
        (center + beak_w / 2, beak_top_y),
        (center, beak_tip_y)
    ], fill=(245, 158, 11, 255))

    # Cyber Chevrons
    ch_y = canvas_size * 0.76
    draw.line([(center - scale * 6, ch_y), (center, ch_y + scale * 4), (center + scale * 6, ch_y)], fill=(56, 189, 248, 200), width=max(1, int(1.5 * scale)))

    # Downsample with Lanczos for smooth subpixel rendering
    resampled = img.resize((size, size), Image.Resampling.LANCZOS)
    out_path = icons_dir / filename
    resampled.save(out_path, "PNG")
    print(f"Generated {out_path} ({size}x{size})")

render_cyber_owl(16, "icon16.png")
render_cyber_owl(32, "icon32.png")
render_cyber_owl(48, "icon48.png")
render_cyber_owl(128, "icon128.png")
print("All brand assets successfully generated!")

