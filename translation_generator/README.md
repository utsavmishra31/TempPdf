# English PDF to Spanish Translation Generator

A local Streamlit app that converts English certificate PDFs into Spanish translation outputs by extracting structured fields and filling prewritten Spanish DOCX templates.

Supported document types:
- Police Clearance Certificate (PCC)
- Birth Certificate
- Marriage Certificate
- Medical Certificate

Current pilot mode in this workspace:
- Active in app flow now: PCC and Birth
- Marriage and Medical extractors exist but are temporarily inactive until their templates are added and validated

Dynamic placeholder configuration:
- Placeholder mapping and template path candidates now come from `config/template_profiles.json`
- You can add/update placeholders and template candidate filenames without code changes
- The Streamlit app includes a JSON profile editor in the preflight section

The app does template autofill, not freeform full-document translation.

## Features

- PDF upload and processing
- Rule-based document type detection
- Direct PDF text extraction with OCR fallback for scanned/image PDFs
- Document-specific field extraction
- Editable extracted fields before output generation
- DOCX template placeholder replacement
- DOCX to PDF conversion via LibreOffice headless
- Download generated DOCX and PDF

## Project Structure

```text
translation_generator/
├─ app.py
├─ requirements.txt
├─ README.md
├─ .env.example
├─ templates/
│  ├─ pcc_template.docx
│  ├─ birth_template.docx
│  ├─ marriage_template.docx
│  └─ medical_template.docx
├─ uploads/
├─ output/
├─ logs/
├─ classifiers/
│  ├─ __init__.py
│  └─ detect_document_type.py
├─ extractors/
│  ├─ __init__.py
│  ├─ pcc_extractor.py
│  ├─ birth_extractor.py
│  ├─ marriage_extractor.py
│  └─ medical_extractor.py
├─ schemas/
│  ├─ __init__.py
│  ├─ pcc_schema.py
│  ├─ birth_schema.py
│  ├─ marriage_schema.py
│  └─ medical_schema.py
├─ services/
│  ├─ __init__.py
│  ├─ pdf_reader.py
│  ├─ ocr_reader.py
│  ├─ text_normalizer.py
│  ├─ template_filler.py
│  ├─ pdf_exporter.py
│  └─ filename_builder.py
└─ utils/
   ├─ __init__.py
   ├─ regex_helpers.py
   └─ logger.py
```

## Installation

1. Create and activate a virtual environment.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

2. Install Python dependencies.

```bash
pip install -r requirements.txt
```

3. Copy environment template.

```bash
cp .env.example .env
```

## System Dependencies

### macOS

Install Tesseract OCR:

```bash
brew install tesseract
```

Install Poppler (required by pdf2image):

```bash
brew install poppler
```

Install LibreOffice for DOCX to PDF conversion:

```bash
brew install --cask libreoffice
```

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y tesseract-ocr poppler-utils libreoffice
```

### Windows

- Install Tesseract from official installer and set `TESSERACT_CMD` in `.env`.
- Install Poppler binaries and set `POPPLER_PATH` in `.env`.
- Install LibreOffice and set `LIBREOFFICE_BIN` if `soffice` is not on PATH.

## Template Setup

Place your Spanish templates in `templates/` with exact names:

- `templates/pcc_template.docx`
- `templates/birth_template.docx`
- `templates/marriage_template.docx`
- `templates/medical_template.docx`

Current compatibility for your uploaded files:

- PCC: `templates/pcc_template.docx` or `templates/pcctemp.docx`
- Birth: `templates/birth_template.docx` or `templates/BIRTH.docx`

Template placeholders can include values like `<<CERT_NO>>`, `<<NAME>>`, etc. Placeholders are mapped from extracted fields via `config/template_profiles.json`.

Important:

- Use real DOCX templates. Invalid or empty DOCX files will fail preflight checks.
- Keep template placeholders synchronized with `PLACEHOLDER_MAP`.
- The app now runs a preflight check and blocks generation if expected placeholders are missing.

Suggested validation workflow:

1. Start with PCC only and test 3-5 real PDFs.
2. Verify extracted fields in the editable form.
3. Verify preflight placeholder audit output.
4. Generate DOCX/PDF and inspect results.
5. Expand to Birth, Marriage, and Medical after PCC is stable.

Audit behavior:

- Presence check is "at least once" per expected placeholder.
- Repeated placeholders are valid and not treated as errors.
- Placeholder scan covers all `word/*.xml` parts (paragraphs, tables, headers/footers, and text-box XML content).

## Run the App

```bash
streamlit run app.py
```

## LibreOffice Quick Check

Before app testing, validate DOCX to PDF conversion manually:

```bash
soffice --headless --convert-to pdf your_test.docx --outdir output
```

## How to Add a New Document Type

1. Add a schema in `schemas/`.
2. Add extractor in `extractors/` that returns normalized field dict.
3. Add detection keywords in `classifiers/detect_document_type.py`.
4. Add template mapping and placeholder mapping in `app.py`.
5. Add template file in `templates/`.

## Notes

- If document type is unknown, app does not crash and allows manual override.
- Missing fields are returned as empty strings and can be edited in UI.
- OCR is used automatically if direct extraction is short/low quality.
