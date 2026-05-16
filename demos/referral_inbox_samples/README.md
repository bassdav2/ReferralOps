# Referral Inbox Samples

Synthetic PDFs for the lean hackathon demo.

- `001_kardiologie_complete_referral.pdf`: selectable PDF text; should pass PyPDF extraction and fill the main fields.
- `002_innere_medizin_missing_phone_scan.pdf`: image-only scan-style PDF; should trigger OCR fallback and leave the patient phone empty for correction.

These are synthetic test documents only. They contain no real patient data.
