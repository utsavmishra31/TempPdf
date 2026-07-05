"""
Apostille Sticker Reader
========================
Standalone tool for reading the embossed apostille sticker (stamp number and date)
from Indian PCC page 2.

Run with:
    /Users/utsav/Desktop/tempPdf/.venv/bin/streamlit run apostille_reader.py
"""
from __future__ import annotations

import re
import shutil
from io import BytesIO
from pathlib import Path

import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

st.set_page_config(page_title="Apostille Sticker Reader", layout="wide")
st.title("🔍 Apostille Sticker Reader")
st.caption("Upload a PCC PDF → adjust image settings → read stamp number and date from the apostille sticker")

# ── helpers ──────────────────────────────────────────────────────────────────

def _find_poppler() -> str | None:
    if shutil.which("pdftoppm"):
        return None
    for d in ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]:
        if Path(d, "pdftoppm").exists():
            return d
    return None


def _extract_page(pdf_bytes: bytes, page_num: int, dpi: int) -> Image.Image | None:
    try:
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(
            pdf_bytes, dpi=dpi,
            first_page=page_num, last_page=page_num,
            poppler_path=_find_poppler(),
        )
        return pages[0] if pages else None
    except Exception as exc:
        st.error(f"Could not render page {page_num}: {exc}")
        return None


def _preprocess(img: Image.Image, settings: dict) -> Image.Image:
    """Apply the chosen preprocessing pipeline to a PIL image."""
    out = img.convert("RGB")

    # Rotate
    angle = settings["angle"]
    if angle != 0:
        out = out.rotate(angle, expand=True, fillcolor=(255, 255, 255))

    # Grayscale
    out = ImageOps.grayscale(out)

    # Autocontrast
    if settings["autocontrast"]:
        out = ImageOps.autocontrast(out, cutoff=settings["ac_cutoff"])

    # Sharpen
    for _ in range(settings["sharpen_passes"]):
        out = out.filter(ImageFilter.SHARPEN)

    # Denoise (median-like using MaxFilter on inverted = erosion on dark text)
    if settings["denoise"]:
        out = out.filter(ImageFilter.MedianFilter(size=settings["denoise_size"]))

    # Threshold / binarize
    if settings["threshold"] > 0:
        thr = settings["threshold"]
        out = out.point(lambda p: 255 if p > thr else 0)

    # Invert
    if settings["invert"]:
        out = ImageOps.invert(out)

    # Upscale for OCR
    scale = settings["upscale"]
    if scale > 1:
        out = out.resize((out.width * scale, out.height * scale), Image.LANCZOS)

    return out


def _run_ocr(img: Image.Image, psm: int, whitelist: str) -> str:
    try:
        import pytesseract
        config = f"--oem 3 --psm {psm}"
        if whitelist:
            config += f" -c tessedit_char_whitelist={whitelist}"
        return pytesseract.image_to_string(img, config=config).strip()
    except Exception as exc:
        return f"[OCR error: {exc}]"


def _highlight_patterns(text: str) -> str:
    """Return text with stamp/date patterns bolded (markdown)."""
    # Stamp: 0I or OI followed by 6-9 digits
    text = re.sub(r"([O0]I\s*[0-9]{6,9})", r"**\1**", text)
    # Date: DD-Mon-YYYY or DD/MM/YYYY or Spanish
    text = re.sub(
        r"(\b\d{1,2}[\-/\s]\d{1,2}[\-/\s]20\d{2}\b"
        r"|\b\d{1,2}[\-\s](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\-\s]20\d{2}\b"
        r"|\b\d{1,2}\s+de\s+\w+\s+de\s+20\d{2}\b)",
        r"**\1**", text, flags=re.IGNORECASE,
    )
    return text


def _to_png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


# ── sidebar: upload ───────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📄 PDF Upload")
    uploaded = st.file_uploader("Upload PCC PDF", type=["pdf"])
    page_num = st.number_input("Page number (apostille is usually page 2)", min_value=1, max_value=10, value=2)
    dpi = st.select_slider("Render DPI", options=[150, 200, 250, 300, 400, 500], value=300)

    st.divider()
    st.header("✂️ Crop region (% of page)")
    crop_left   = st.slider("Left %",   0, 100,  0)
    crop_top    = st.slider("Top %",    0, 100, 45)
    crop_right  = st.slider("Right %",  0, 100, 100)
    crop_bottom = st.slider("Bottom %", 0, 100, 100)

    st.divider()
    st.header("🎛️ Image processing")
    angle           = st.slider("Rotation angle (°)", -15, 15, 0)
    autocontrast    = st.checkbox("Auto-contrast", value=True)
    ac_cutoff       = st.slider("Auto-contrast cutoff %", 0, 10, 1) if autocontrast else 0
    sharpen_passes  = st.slider("Sharpen passes", 0, 5, 2)
    denoise         = st.checkbox("Median denoise", value=False)
    denoise_size    = st.select_slider("Denoise kernel", [3, 5, 7], value=3) if denoise else 3
    threshold       = st.slider("Binarize threshold (0 = off)", 0, 255, 0)
    invert          = st.checkbox("Invert colours", value=False)
    upscale         = st.select_slider("Upscale ×", [1, 2, 3, 4], value=2)

    st.divider()
    st.header("🔡 OCR settings")
    psm_options = {
        "6 — Block of text (default)": 6,
        "7 — Single line": 7,
        "11 — Sparse text": 11,
        "13 — Raw line": 13,
    }
    psm_label  = st.selectbox("Tesseract PSM mode", list(psm_options.keys()))
    psm        = psm_options[psm_label]
    use_whitelist = st.checkbox("Restrict to digits + O/I (stamp mode)", value=False)
    whitelist  = "0123456789OI " if use_whitelist else ""

    run_all_psm = st.checkbox("Run all PSM modes and show all results", value=False)


# ── main panel ────────────────────────────────────────────────────────────────

if not uploaded:
    st.info("👈  Upload a PDF in the sidebar to get started.")
    st.stop()

pdf_bytes = uploaded.read()

with st.spinner(f"Rendering page {page_num} at {dpi} DPI…"):
    page = _extract_page(pdf_bytes, page_num, dpi)

if page is None:
    st.stop()

# Apply crop
w, h = page.size
x1 = int(w * crop_left   / 100)
y1 = int(h * crop_top    / 100)
x2 = int(w * crop_right  / 100)
y2 = int(h * crop_bottom / 100)
if x2 <= x1 or y2 <= y1:
    st.error("Invalid crop — right must be > left and bottom must be > top.")
    st.stop()

cropped = page.crop((x1, y1, x2, y2))

settings = dict(
    angle=angle, autocontrast=autocontrast, ac_cutoff=ac_cutoff,
    sharpen_passes=sharpen_passes, denoise=denoise, denoise_size=denoise_size,
    threshold=threshold, invert=invert, upscale=upscale,
)
processed = _preprocess(cropped, settings)

# ── display ──────────────────────────────────────────────────────────────────

col_orig, col_proc = st.columns(2)
with col_orig:
    st.subheader("Original crop")
    st.image(_to_png_bytes(cropped), use_container_width=True)

with col_proc:
    st.subheader("Processed crop")
    st.image(_to_png_bytes(processed), use_container_width=True)

st.divider()

# ── OCR results ───────────────────────────────────────────────────────────────

st.subheader("🔡 OCR results")

if run_all_psm:
    cols = st.columns(4)
    for i, (label, p) in enumerate(psm_options.items()):
        ocr_result = _run_ocr(processed, p, whitelist)
        highlighted = _highlight_patterns(ocr_result)
        with cols[i % 4]:
            st.markdown(f"**PSM {p}**")
            st.markdown(highlighted if highlighted else "_nothing detected_")
            st.caption(f"raw: `{ocr_result[:120]}`")
else:
    ocr_result = _run_ocr(processed, psm, whitelist)
    highlighted = _highlight_patterns(ocr_result)
    if highlighted:
        st.markdown(highlighted)
    else:
        st.info("No text detected. Try adjusting the crop, threshold, or PSM mode.")
    with st.expander("Raw OCR output"):
        st.code(ocr_result)

# ── pattern scanner ───────────────────────────────────────────────────────────

st.divider()
st.subheader("🎯 Pattern scan across all preprocessing presets")
st.caption("Automatically tries many combinations and shows any stamp/date patterns found.")

if st.button("🚀 Run pattern scan (takes ~10 seconds)"):
    found: list[dict] = []
    presets = []
    for _angle in [-5, -3, 0, 3, 5]:
        for _thr in [0, 110, 130, 150, 170]:
            for _inv in [False, True]:
                for _sharp in [0, 2]:
                    presets.append(dict(
                        angle=_angle, autocontrast=True, ac_cutoff=1,
                        sharpen_passes=_sharp, denoise=False, denoise_size=3,
                        threshold=_thr, invert=_inv, upscale=2,
                    ))

    progress = st.progress(0)
    for idx, preset in enumerate(presets):
        progress.progress((idx + 1) / len(presets))
        img = _preprocess(cropped, preset)
        for p in [6, 7, 11]:
            for wl in ["", "0123456789OI "]:
                txt = _run_ocr(img, p, wl)
                stamps = re.findall(r"[O0]I\s*[0-9]{6,9}", txt)
                dates  = re.findall(
                    r"\b\d{1,2}[\-/]\d{1,2}[\-/]20\d{2}\b"
                    r"|\b\d{1,2}[\-\s](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\-\s]20\d{2}\b",
                    txt, flags=re.I,
                )
                if stamps or dates:
                    found.append({
                        "angle": preset["angle"], "threshold": preset["threshold"],
                        "invert": preset["invert"], "sharpen": preset["sharpen_passes"],
                        "psm": p, "whitelist": bool(wl),
                        "stamps": stamps, "dates": dates, "snippet": txt[:120],
                    })
    progress.empty()

    if found:
        st.success(f"Found {len(found)} matching result(s)!")
        stamp_hits = [r for r in found if r["stamps"]]
        date_hits  = [r for r in found if r["dates"]]

        if stamp_hits:
            st.markdown("**Stamp number candidates:**")
            seen: set[str] = set()
            for r in stamp_hits:
                for s in r["stamps"]:
                    if s not in seen:
                        seen.add(s)
                        st.code(f"{s}  ← angle={r['angle']}° thr={r['threshold']} inv={r['invert']} psm={r['psm']}")

        if date_hits:
            st.markdown("**Date candidates:**")
            seen_d: set[str] = set()
            for r in date_hits:
                for d in r["dates"]:
                    if d not in seen_d:
                        seen_d.add(d)
                        st.code(f"{d}  ← angle={r['angle']}° thr={r['threshold']} inv={r['invert']} psm={r['psm']}")

        with st.expander("All raw results"):
            for r in found:
                st.json(r)
    else:
        st.warning(
            "No stamp or date patterns found in any preprocessing combination. "
            "The sticker text is too obscured for automatic OCR. "
            "Read the values from the image above and enter them manually."
        )

# ── full page reference ───────────────────────────────────────────────────────

with st.expander("View full page"):
    st.image(_to_png_bytes(ImageOps.autocontrast(ImageOps.grayscale(page))),
             caption=f"Full page {page_num} (greyscale, autocontrast)", use_container_width=True)
