import { Button, Select, SelectItem, Tag, TextArea, TextInput } from "@carbon/react";
import { Checkmark, Close, Document, Help, Renew, Send } from "@carbon/icons-react";
import type { ReferralCase, ReferralRoutingTarget, ReferralWorklistItem } from "../api/client";
import { text, type UiLanguage } from "../i18n";

type ReviewDecision = "confirm" | "correct" | "reject" | "question";

export type CorrectionDraft = {
  patientName: string;
  birthDate: string;
  phone: string;
  insuranceId: string;
  referringPhysician: string;
  referringOrganization: string;
  reasonForReferral: string;
  routingTarget: string;
  comment: string;
};

type Props = {
  item: ReferralWorklistItem | null;
  currentCase: ReferralCase | null;
  correctionDraft: CorrectionDraft;
  routingTargets: ReferralRoutingTarget[];
  language: UiLanguage;
  loading: boolean;
  disabled: boolean;
  reanalyzeDisabled: boolean;
  onAnalyze: () => void;
  onReview: (decision: ReviewDecision) => void;
  onWriteback: () => void;
  onCorrectionDraftChange: (field: keyof CorrectionDraft, value: string) => void;
};

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${Math.round(value * 100)}%`;
}

const FIELD_LABELS: Record<string, { de: string; en: string }> = {
  "patient.name": { de: "Patientenname", en: "Patient name" },
  "patient.birth_date": { de: "Geburtsdatum", en: "Birth date" },
  "patient.phone": { de: "Telefon Patient", en: "Patient phone" },
  "patient.insurance_id": { de: "Versicherungsnummer", en: "Insurance ID" },
  "referring_party.physician_name": { de: "Zuweisender Arzt", en: "Referring physician" },
  "referring_party.organization": { de: "Zuweisende Organisation", en: "Referring organization" },
  "clinical_context_for_admin_routing.reason_for_referral": { de: "Grund der Zuweisung", en: "Reason for referral" },
  "routing_proposal.routing_target": { de: "Zielroute", en: "Target route" },
  "attachments.lab": { de: "Laborbeilage", en: "Lab attachment" },
  "attachments.imaging": { de: "Bildgebung", en: "Imaging attachment" },
  "attachments.medication_list": { de: "Medikamentenliste", en: "Medication list" },
  "attachments.prior_reports": { de: "Vorberichte", en: "Prior reports" },
  "attachments.consent_form": { de: "Einwilligung", en: "Consent form" }
};

const SEVERITY_LABELS: Record<string, { de: string; en: string }> = {
  blocking: { de: "Pflichtangabe", en: "Required" },
  recommended: { de: "Empfohlen", en: "Recommended" },
  info: { de: "Hinweis", en: "Info" }
};
const WRITEBACK_ALLOWED_STATUSES = new Set(["review_confirm", "review_correct"]);

function fieldLabel(value: string, language: UiLanguage) {
  const label = FIELD_LABELS[value];
  if (label) return text(language, label.de, label.en);
  return value
    .split(".")
    .map((part) => part.split("_").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" "))
    .join(" / ");
}

function severityLabel(value: string, language: UiLanguage) {
  const label = SEVERITY_LABELS[value];
  return label ? text(language, label.de, label.en) : value;
}

export function ReferralAnalysisPane({
  item,
  currentCase,
  correctionDraft,
  routingTargets,
  language,
  loading,
  disabled,
  reanalyzeDisabled,
  onAnalyze,
  onReview,
  onWriteback,
  onCorrectionDraftChange
}: Props) {
  if (!item) {
    return (
      <>
        <div className="pane-header">
          <h2>{text(language, "Analyse", "Analysis")}</h2>
        </div>
        <div className="pane-body">
          <div className="empty-state">{text(language, "Waehle ein Dokument aus der Arbeitsliste.", "Select a document from the worklist.")}</div>
        </div>
      </>
    );
  }

  if (loading && !currentCase) {
    return (
      <>
        <div className="pane-header">
          <h2>{text(language, "Analyse", "Analysis")}</h2>
          <span className="eyebrow">{item.document_title}</span>
        </div>
        <div className="pane-body">
          <div className="empty-state action-empty">
            <strong>{text(language, "Analyse wird geladen", "Analysis loading")}</strong>
            <span>{text(language, "Die Detaildaten fuer dieses Dokument werden geoeffnet.", "Opening the details for this document.")}</span>
          </div>
        </div>
      </>
    );
  }

  if (!currentCase) {
    return (
      <>
        <div className="pane-header">
          <h2>{text(language, "Analyse", "Analysis")}</h2>
          <span className="eyebrow">{text(language, "Analyse ausstehend", "Analysis pending")}</span>
        </div>
        <div className="pane-body">
          <div className="empty-state action-empty">
            <strong>{text(language, "Analyse laeuft oder ist eingereiht", "Analysis running or queued")}</strong>
            <span>
              {text(
                language,
                "Die PDF-Inbox analysiert dieses Dokument automatisch. Das Ergebnis erscheint hier, sobald Gemma fertig ist.",
                "The PDF inbox analyzes this document automatically. The result appears here when Gemma is done."
              )}
            </span>
          </div>
        </div>
      </>
    );
  }

  const analysis = currentCase.analysis;
  const writebackAllowed = WRITEBACK_ALLOWED_STATUSES.has(currentCase.status);
  const referringPartyLabel =
    analysis.referring_party.physician_name ?? analysis.referring_party.organization ?? text(language, "Unklar", "Unknown");

  return (
    <>
      <div className="pane-header">
        <h2>{text(language, "Analyse", "Analysis")}</h2>
        <div className="button-row">
          <Tag size="sm" type={analysis.human_review_required ? "red" : "green"}>
            {analysis.human_review_required ? text(language, "Review noetig", "Review required") : text(language, "Review optional", "Review optional")}
          </Tag>
          <Button
            kind="ghost"
            title={text(language, "Erneut analysieren", "Reanalyze")}
            onClick={onAnalyze}
            disabled={reanalyzeDisabled}
            renderIcon={Document}
            size="sm"
            type="button"
          >
            {text(language, "Erneut analysieren", "Reanalyze")}
          </Button>
        </div>
      </div>
      <div className="pane-body">
        <div className="decision-row">
          <div>
            <span className="eyebrow">{text(language, "Routing-Vorschlag", "Routing proposal")}</span>
            <h2>{analysis.routing_proposal.department ?? text(language, "Menschliche Pruefung", "Human review")}</h2>
            <small>{analysis.routing_proposal.routing_target ?? text(language, "Keine eindeutige Zielroute", "No clear target route")}</small>
          </div>
          <span className="confidence">{formatPercent(analysis.routing_proposal.confidence)}</span>
        </div>

        <div className="field-grid">
          <div>
            <span>{text(language, "Patient", "Patient")}</span>
            <strong>{analysis.patient.name ?? text(language, "Unklar", "Unknown")}</strong>
          </div>
          <div>
            <span>{text(language, "Geburtsdatum", "Birth date")}</span>
            <strong>{analysis.patient.birth_date ?? text(language, "Unklar", "Unknown")}</strong>
          </div>
          <div>
            <span>{text(language, "Zuweisende Stelle", "Referring party")}</span>
            <strong>{referringPartyLabel}</strong>
          </div>
          <div>
            <span>Review</span>
            <strong>{analysis.human_review_required ? text(language, "Erforderlich", "Required") : text(language, "Nicht erforderlich", "Not required")}</strong>
          </div>
        </div>

        <div className="correction-panel">
          <div className="correction-grid">
            <TextInput
              id="correction-patient-name"
              labelText={text(language, "Patient", "Patient")}
              size="md"
              value={correctionDraft.patientName}
              onChange={(event) => onCorrectionDraftChange("patientName", event.target.value)}
            />
            <TextInput
              id="correction-birth-date"
              labelText={text(language, "Geburtsdatum", "Birth date")}
              size="md"
              type="date"
              value={correctionDraft.birthDate}
              onChange={(event) => onCorrectionDraftChange("birthDate", event.target.value)}
            />
            <TextInput
              id="correction-phone"
              labelText={text(language, "Telefon", "Phone")}
              size="md"
              value={correctionDraft.phone}
              onChange={(event) => onCorrectionDraftChange("phone", event.target.value)}
            />
            <TextInput
              id="correction-insurance-id"
              labelText={text(language, "Versicherungsnummer", "Insurance ID")}
              size="md"
              value={correctionDraft.insuranceId}
              onChange={(event) => onCorrectionDraftChange("insuranceId", event.target.value)}
            />
            <TextInput
              id="correction-referring-physician"
              labelText={text(language, "Zuweisende Aerztin/Arzt", "Referring physician")}
              size="md"
              value={correctionDraft.referringPhysician}
              onChange={(event) => onCorrectionDraftChange("referringPhysician", event.target.value)}
            />
            <TextInput
              id="correction-referring-organization"
              labelText={text(language, "Zuweisende Organisation", "Referring organization")}
              size="md"
              value={correctionDraft.referringOrganization}
              onChange={(event) => onCorrectionDraftChange("referringOrganization", event.target.value)}
            />
            <Select
              id="correction-routing-target"
              labelText={text(language, "Zielroute", "Target route")}
              size="md"
              value={correctionDraft.routingTarget}
              onChange={(event) => onCorrectionDraftChange("routingTarget", event.target.value)}
            >
              <SelectItem value="" text={text(language, "Route waehlen", "Select route")} />
              {routingTargets.map((target) => (
                <SelectItem value={target.routing_target} text={target.department} key={target.routing_target} />
              ))}
            </Select>
            <TextInput
              id="correction-reason"
              labelText={text(language, "Grund der Zuweisung", "Reason for referral")}
              size="md"
              value={correctionDraft.reasonForReferral}
              onChange={(event) => onCorrectionDraftChange("reasonForReferral", event.target.value)}
            />
            <TextArea
              className="correction-comment"
              id="correction-comment"
              labelText={text(language, "Kommentar / Rueckfrage", "Comment / question")}
              rows={4}
              value={correctionDraft.comment}
              onChange={(event) => onCorrectionDraftChange("comment", event.target.value)}
            />
          </div>
        </div>

        <h3>{text(language, "Warnungen", "Warnings")}</h3>
        <ul className="worklist compact-list">
          {analysis.warnings.length === 0 ? (
            <li><small>{text(language, "Keine Warnungen.", "No warnings.")}</small></li>
          ) : (
            analysis.warnings.map((warning) => (
              <li key={warning}>
                <span>{text(language, "Warnung", "Warning")}</span>
                <small>{warning}</small>
              </li>
            ))
          )}
        </ul>

        <h3>{text(language, "Fehlende Angaben", "Missing information")}</h3>
        <ul className="worklist compact-list">
          {analysis.missing_items.length === 0 ? (
            <li><small>{text(language, "Keine fehlenden Pflichtangaben erkannt.", "No missing required information detected.")}</small></li>
          ) : (
            analysis.missing_items.map((missing) => (
              <li key={`${missing.field}-${missing.severity}`}>
                <span className={missing.severity}>{severityLabel(missing.severity, language)}</span>
                <strong>{fieldLabel(missing.field, language)}</strong>
                <small>{missing.reason}</small>
              </li>
            ))
          )}
        </ul>

        <h3>{text(language, "Evidenz", "Evidence")}</h3>
        <ul className="worklist compact-list">
          {analysis.evidence.length === 0 ? (
            <li><small>{text(language, "Keine Evidenzstellen gefunden.", "No evidence snippets found.")}</small></li>
          ) : (
            analysis.evidence.map((evidence) => (
              <li key={`${evidence.claim}-${evidence.page ?? "none"}`}>
                <span>{text(language, "Seite", "Page")} {evidence.page ?? "?"}</span>
                <strong>{evidence.claim}</strong>
                <small>{evidence.quote}</small>
              </li>
            ))
          )}
        </ul>
      </div>

      <div className="pane-footer action-row">
        <Button title={text(language, "Freigeben", "Approve")} onClick={() => onReview("confirm")} disabled={disabled} renderIcon={Checkmark} size="md" type="button">
          {text(language, "Freigeben", "Approve")}
        </Button>
        <Button kind="secondary" title={text(language, "Korrigieren und freigeben", "Correct and approve")} onClick={() => onReview("correct")} disabled={disabled} renderIcon={Renew} size="md" type="button">
          {text(language, "Korrigieren & Freigeben", "Correct & approve")}
        </Button>
        <Button kind="tertiary" title={text(language, "Rueckfrage stellen", "Ask question")} onClick={() => onReview("question")} disabled={disabled} renderIcon={Help} size="md" type="button">
          {text(language, "Rueckfrage stellen", "Ask question")}
        </Button>
        <Button kind="danger" title={text(language, "Ablehnen", "Reject")} onClick={() => onReview("reject")} disabled={disabled} renderIcon={Close} size="md" type="button">
          {text(language, "Ablehnen", "Reject")}
        </Button>
        <Button kind="ghost" title={text(language, "Weiterleiten", "Forward")} onClick={onWriteback} disabled={disabled || !writebackAllowed} renderIcon={Send} size="md" type="button">
          {text(language, "Weiterleiten", "Forward")}
        </Button>
      </div>
    </>
  );
}
