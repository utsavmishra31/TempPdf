# Manual Translation Template Filler

A frontend-only browser app for filling Spanish translation DOCX templates manually. The app does not run OCR, does not upload source PDFs, and does not require a Python backend.

Supported templates:
- PCC Jalandhar
- PCC Chandigarh
- Medical
- Birth
- Marriage

## Features

- Template dropdown on the first screen
- Automatic placeholder detection from the selected DOCX file
- Bulk Paste tab for entries like `<<NAME>> = UTSAV MISHRA, <<CERT_NO>> = CD1234567654`
- Empty text fields for each `<<PLACEHOLDER>>`
- Dropdown plus custom text controls for common PCC/Medical values such as title, relation, and PCC type
- MS Word download with placeholders replaced by typed text
- PDF download generated in the browser from the rendered document preview

## Project Structure

```text
translation_generator/
├─ index.html
├─ app.js
├─ styles.css
├─ README.md
└─ templates/
   ├─ BIRTH.docx
   ├─ MARRIAGE.docx
   ├─ MEDICAL.docx
   ├─ pccChandigarh.docx
   └─ pccjalandhar.docx
```

## Template Setup

Place DOCX templates in `templates/`. The frontend reads `<<PLACEHOLDER>>` values directly from the selected DOCX file, so no separate mapping file is required.

## Run the App

```bash
python3 -m http.server 8080 --directory /Users/utsav/Desktop/tempPdf/translation_generator
```

Open `http://127.0.0.1:8080/` in a browser.

## Add a New Template

1. Add the `.docx` file under `templates/`.
2. Add one entry to `TEMPLATE_OPTIONS` in `app.js`.
3. Use placeholders in the `<<NAME>>` format inside the DOCX.

## Notes

- Opening `index.html` directly from Finder may block template loading. Use the local static server command above.
- DOCX output keeps the original template file structure and replaces placeholders inside Word XML.
- PDF output is generated from the browser-rendered preview. Inspect the DOCX when exact legal formatting is required.
