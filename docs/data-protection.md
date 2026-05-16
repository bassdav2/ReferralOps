# Data Protection

This repository is for synthetic demo data. A real hospital pilot needs a formal privacy, security, and regulatory review before any production or patient-data use.

## Stored Data

- Document registry metadata.
- Extracted page text.
- Access groups.
- Referral analysis JSON.
- Guideline chunks and embeddings.
- Chat answers and feedback.
- Audit events with hashes and decision snapshots.

## Not Stored By Default

- Secrets.
- External AI API credentials.
- Local model API keys entered through the UI. If a local gateway needs a key, set `LOCAL_LLM_API_KEY` in the environment; `data/local_model_config.json` stores only non-secret endpoint settings.
- Production patient exports.
- Prompt text when `STORE_PROMPT_TEXT=false`.
- Writeback payloads unless enabled and reviewed.

## Controls

- `NO_EXTERNAL_AI_CALLS=true` by default.
- ACL checks before document display and retrieval.
- Demo data is synthetic.
- Writeback is disabled by default.
- Prompt/output logs are treated as sensitive.

## Medical Device Boundary

The purpose is administrative support. The assistant does not diagnose, treat, monitor, predict, discharge, prioritize clinically, or autonomously decide patient management. Hospitals must still check the regulatory classification before a pilot.
