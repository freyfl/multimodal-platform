#!/usr/bin/env python3
"""Extract existing project font faces only; never reuse application JS or CSS."""

from pathlib import Path
import base64
import hashlib
import re


def main():
    root = Path(__file__).resolve().parent.parent
    assets = root / "frontend/dist/assets"
    output = root / "docs/fonts"
    faces = []
    files = {}
    families = set()
    # Vite output has flat @font-face declarations without nested CSS rules.
    for stylesheet in sorted(assets.glob("*.css")):
        for body in re.findall(r"@font-face\s*\{([^{}]+)\}", stylesheet.read_text()):
            family = re.search(r"font-family\s*:\s*([^;]+)", body)
            weight = re.search(r"font-weight\s*:\s*(\d+)", body)
            if not family or not weight or weight[1] not in {"400", "700"}:
                continue
            name = family[1].strip().strip("\"'")
            if name not in {"Noto Sans SC", "Exo 2"}:
                continue
            urls = re.findall(r"url\(\s*[\"']?([^\"')\s]+)[\"']?\s*\)", body)
            fonts = [url for url in urls if url.endswith(".woff2") or url.startswith("data:font/woff2;base64,")]
            if not fonts:
                raise SystemExit(f"Missing WOFF2 face for {name}")
            if fonts[0].startswith("data:"):
                data = base64.b64decode(fonts[0].split(",", 1)[1], validate=True)
                filename = "inline-" + hashlib.sha256(data).hexdigest()[:16] + ".woff2"
            else:
                filename = Path(fonts[0]).name
                source = assets / filename
                if source.is_symlink() or not source.is_file():
                    raise SystemExit("Missing or symlinked local font asset")
                data = source.read_bytes()
            src = f"src:url('./fonts/{filename}') format('woff2')"
            unicode_range = re.search(r"unicode-range\s*:[^;]+", body)
            local = (
                f"font-family:'{name}';font-style:normal;font-display:swap;"
                f"font-weight:{weight[1]};{src};"
                + (unicode_range[0] + ";" if unicode_range else "")
            )
            if re.search(r"url\([^)]*(?:https?:|//)", local):
                raise SystemExit("External font URL rejected")
            faces.append("@font-face {" + local + "}")
            files[filename] = data
            families.add(name)
    if families != {"Noto Sans SC", "Exo 2"}:
        raise SystemExit("Build must contain local Noto Sans SC and Exo 2 font faces")
    output.mkdir(parents=True, exist_ok=True)
    for filename, data in files.items():
        (output / filename).write_bytes(data)
    (root / "docs/fonts.css").write_text(
        "/* Generated from project font assets; no external requests. */\n"
        + "\n".join(dict.fromkeys(faces)) + "\n"
    )
    print(f"Extracted {len(files)} local font files; application assets were not copied.")


if __name__ == "__main__":
    main()
