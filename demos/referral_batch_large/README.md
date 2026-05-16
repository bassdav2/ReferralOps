# Large Referral Batch

This folder contains the larger synthetic referral PDF batch for dashboard tests and optional model evaluation.

Layout:

```text
demos/referral_batch_large/pdfs/*.pdf
demos/referral_batch_large/metadata.csv                # synthetic source metadata
demos/referral_batch_large/pdf_adjudicated_labels.csv  # sanitized PDF-content labels
```

The repository also ships with two smaller smoke-test PDFs in `demos/referral_inbox_samples/` for a fast first run.

To test a batch through the dashboard, drag some or all PDFs from `demos/referral_batch_large/pdfs/` into the PDF inbox, or point `REFERRAL_INBOX_DIR` at this folder.

The PDFs and metadata are synthetic. Do not add real patient data here.

## Evaluation labels

The reported 500-PDF score in `docs/live-500-pdf-review-report.md` uses PDF-content-adjudicated routing labels.

```text
demos/referral_batch_large/pdf_adjudicated_labels.csv
```

`scripts/evaluate_referral_batch.py` uses that adjudicated label file automatically when present. The metadata fallback is for exploratory smoke checks only.
