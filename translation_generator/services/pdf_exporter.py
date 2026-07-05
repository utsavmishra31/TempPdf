from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def is_libreoffice_available() -> tuple[bool, str]:
    libreoffice_bin = os.getenv("LIBREOFFICE_BIN", "soffice")
    resolved = shutil.which(libreoffice_bin)
    if resolved:
        return True, resolved
    return False, libreoffice_bin


def convert_docx_to_pdf(docx_path: str, output_dir: str) -> str:
    libreoffice_bin = os.getenv("LIBREOFFICE_BIN", "soffice")
    output_dir_path = Path(output_dir).resolve()
    output_dir_path.mkdir(parents=True, exist_ok=True)

    cmd = [
        libreoffice_bin,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir_path),
        str(Path(docx_path).resolve()),
    ]

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "LibreOffice executable not found. Install LibreOffice and set LIBREOFFICE_BIN."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "Unknown error"
        raise RuntimeError(f"DOCX to PDF conversion failed: {stderr}") from exc

    expected_pdf = output_dir_path / f"{Path(docx_path).stem}.pdf"
    if not expected_pdf.exists():
        details = result.stdout.strip() or "No output from LibreOffice"
        raise RuntimeError(f"PDF was not generated. Details: {details}")

    return str(expected_pdf)
