# Live 500 PDF Referral Routing Review

Date: 2026-05-12

This report summarizes a synthetic administrative referral-routing evaluation. It is not clinical validation, does not support autonomous diagnosis or treatment decisions, and must not be run on real patient data. Model access stayed behind the local `backend/app/model_gateway` path through an OpenAI-compatible vLLM endpoint.

## Scope

- Dataset: 500 synthetic referral PDFs.
- Configured routing taxonomy in this submission build: 45 possible routing targets.
- PDF-adjudicated routing targets observed in the completed H100 review: 35.
- Model: `google/gemma-4-31B-it` served locally through vLLM on an H100 VPS.
- Evaluation mode: live inference captured once, then rescored from SQLite without rerunning the model.
- Generated run artifacts stay under ignored `reports/` paths. The committed evaluation evidence is limited to the adjudicated labels and a compact metrics summary.

## Method

A PDF-content review pass adjudicated each document from visible or extracted document content, then compared that adjudicated label against the stored Gemma prediction. The model output preserved a free-text suggested destination and mapped routing candidates; scoring normalized those candidates to the controlled routing taxonomy.

The label decision rule was content-first:

1. Use the PDF content, document title, explicit recipient or requested administrative service.
2. Choose exactly one configured `routing_target`.
3. Mark ambiguous cases as `uncertain`.
4. Do not assign labels from file paths, source metadata, or Gemma predictions.
5. Use scripts only for I/O, merging reviewer CSVs, and computing aggregate metrics.

## Main Results

| Metric | Result |
|---|---:|
| PDFs reviewed | 500 |
| Reviewed rows | 474 |
| Uncertain rows | 26 |
| Gemma top-1 vs PDF-adjudicated label | 427 / 500 |
| Gemma top-1 accuracy | 85.4% |
| Gemma top-3 vs PDF-adjudicated label | 459 / 500 |
| Gemma top-3 accuracy | 91.8% |
| Gemma top-1 matches excluding uncertain rows | 416 / 474 |
| Gemma top-1 excluding uncertain rows | 87.8% |
| Schema valid rate | 100.0% |
| Invalid model responses | 0 |
| Null/unknown route rate | 0.0% |
| Safe fallback rate | 0.0% |

## Error Pattern Summary

Largest remaining Gemma top-1 mismatch groups:

| Adjudicated route | Gemma primary route | Count |
|---|---|---:|
| `pflegekoordination` | `allgemeinambulanz` | 17 |
| `notfallnahe_abklaerung` | `allgemeinambulanz` | 9 |
| `kardiologie` | `allgemeinambulanz` | 5 |
| `versicherungskoordination` | `patientenadministration` | 5 |
| `allgemeinambulanz` | `orthopaedie` | 3 |

Interpretation: the model was strong on explicit specialty and diagnostic routing cues, but it still overused broad administrative routes for transfer, near-emergency, and insurance-administration boundaries.

## Spot Checks

- `SYN_CH_0205_diagnostic.pdf`: document requests CT Thorax/Abdomen; adjudicated `radiologie`; Gemma matched.
- `SYN_CH_0030_diagnostic.pdf`: document states Pathologie-Vorbericht; adjudicated `pathologie`; Gemma matched.
- `SYN_CH_0468_diagnostic.pdf`: document is a Laborbericht; adjudicated `laboradministration`; Gemma returned `labor`, which is close but not exact.
- `SYN_CH_0419_specialty_ambulatory.pdf`: document contains gynecology-relevant cues; adjudicated `gynaekologie`; Gemma returned `neurochirurgie`.

## Committed Evidence

The sanitized label file `demos/referral_batch_large/pdf_adjudicated_labels.csv` and aggregate metrics file `docs/live_500_metrics_summary.json` preserve the public, non-prompt, non-extracted-text evaluation record. The committed batch evaluator supports fresh live judge runs against the synthetic batch.
