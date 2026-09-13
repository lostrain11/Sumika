# Format-specific boundaries

## Word

Use `docx.Document(path)` to inspect paragraphs, runs, tables, headers and footers. Preserve styles and relationships when editing an existing file. Setting `paragraph.text` flattens run formatting; prefer run-level changes when formatting matters, and handle matches split across runs deliberately. Not all OOXML constructs, revisions, fields or embedded objects are represented by this API. Reopen the output and check the original features needed by the task; do not promise lossless arbitrary document edits.

Official API: https://python-docx.readthedocs.io/en/latest/

## Excel

Use `openpyxl.load_workbook(path, data_only=False)` for edits so formulas remain formulas. `data_only=True` reads stored results and **does not calculate**. Writing or changing a formula does not populate its cached value. Recalculation requires an actual spreadsheet engine, separately selected and validated; never report `None` or a stale cache as a calculated result.

Use normal mode for edits; use read-only mode for large read tasks. Check sheet names, formulas, types, merged ranges, styles and dimensions after saving. `keep_vba=True` may preserve a VBA archive but is not a macro compatibility guarantee; this baseline validates `.xlsx` only. openpyxl may lose unsupported shapes or extensions. Preserve the original when working on complex workbooks.

Official API: https://openpyxl.readthedocs.io/en/stable/

## PowerPoint

Use `pptx.Presentation(path)` and existing layouts/placeholders. Modify runs when maintaining styling; assigning shape/text-frame text can discard run formatting. Reopen and check slide count, requested text, geometry and relationships. Python-pptx does not render slides or comprehensively model animation and every Office feature. Typography, clipping and overlap require a rendered review. Existing templates should be preserved, not silently replaced with a generic theme.

Official API: https://python-pptx.readthedocs.io/en/latest/

## PDF

Use `pypdf.PdfReader` for text and page inspection, and `PdfWriter` for page assembly, rotation, metadata and overlays. Use `reportlab` to create PDF content with suitable fonts. Chinese text needs an appropriate font; a text-extraction check alone does not validate font availability or display on other systems.

PDF is a page description, not an editable word-processing format. Text extraction order may differ from reading order. Scans require OCR, which is not supplied here. An overlay does not remove underlying text and must never be presented as redaction. Arbitrary in-place paragraph replacement, digital signature preservation, encrypted-document support and secure redaction have not been validated by this baseline. Do not treat failed extraction as an empty document.

Official APIs: https://pypdf.readthedocs.io/ and https://docs.reportlab.com/
