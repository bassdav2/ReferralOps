import type { KeyboardEvent } from "react";
import { Button } from "@carbon/react";
import {
  CheckmarkFilled,
  CloseFilled,
  Document,
  Help,
  Search,
  WarningAltFilled
} from "@carbon/icons-react";
import type { ReferralWorklistFilter, ReferralWorklistItem } from "../api/client";
import { text, type UiLanguage } from "../i18n";
import { ReferralPipelineChips } from "./ReferralPipelineChips";

type Props = {
  items: ReferralWorklistItem[];
  filter: ReferralWorklistFilter;
  selectedDocumentId: string;
  language: UiLanguage;
  disabled: boolean;
  onFilterChange: (filter: ReferralWorklistFilter) => void;
  onSelect: (documentId: string) => void;
};

const FILTERS: Array<{ value: ReferralWorklistFilter; de: string; en: string }> = [
  { value: "active", de: "Aktiv", en: "Active" },
  { value: "all", de: "Alle", en: "All" },
  { value: "new", de: "Neu", en: "New" },
  { value: "review_required", de: "Review noetig", en: "Needs review" },
  { value: "ocr_low", de: "OCR schwach", en: "Weak OCR" },
  { value: "route_unclear", de: "Unklare Route", en: "Unclear route" },
  { value: "confirmed", de: "Bestaetigt", en: "Approved" },
  { value: "rejected", de: "Zurueckgewiesen", en: "Rejected" }
];

function statusLabel(status: string, language: UiLanguage) {
  if (status === "new") return text(language, "Neu", "New");
  if (status === "analysis_ready") return text(language, "Analysiert", "Analyzed");
  if (status === "review_confirm") return text(language, "Bestaetigt", "Approved");
  if (status === "review_correct") return text(language, "Korrigiert", "Corrected");
  if (status === "review_reject") return text(language, "Zurueckgewiesen", "Rejected");
  if (status === "review_question") return text(language, "Rueckfrage", "Question");
  if (status === "writeback_sent") return text(language, "Weitergeleitet", "Forwarded");
  return status;
}

function RowIcon({ item }: { item: ReferralWorklistItem }) {
  if (item.status === "review_confirm") return <CheckmarkFilled size={16} />;
  if (item.status === "review_reject") return <CloseFilled size={16} />;
  if (item.ocr_status === "low" || item.ocr_status === "failed") return <WarningAltFilled size={16} />;
  if (!item.routing_target || (item.confidence ?? 0) < 0.6) return <Search size={16} />;
  if (item.status === "new") return <Document size={16} />;
  return <Help size={16} />;
}

export function ReferralWorklistTable({
  items,
  filter,
  selectedDocumentId,
  language,
  disabled,
  onFilterChange,
  onSelect
}: Props) {
  const selectItem = (documentId: string) => {
    if (!disabled) {
      onSelect(documentId);
    }
  };

  const handleRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, documentId: string) => {
    if (disabled) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(documentId);
    }
  };

  return (
    <>
      <div className="pane-header">
        <h2>{text(language, "Arbeitsliste", "Worklist")}</h2>
        <span className="eyebrow">{items.length} {text(language, "Eintraege", "items")}</span>
      </div>
      <div className="filter-bar" aria-label="Referral filters">
        {FILTERS.map((entry) => (
          <Button
            className={entry.value === filter ? "active" : ""}
            disabled={disabled}
            kind={entry.value === filter ? "primary" : "tertiary"}
            key={entry.value}
            onClick={() => onFilterChange(entry.value)}
            size="sm"
            type="button"
          >
            {text(language, entry.de, entry.en)}
          </Button>
        ))}
      </div>
      <div className="worklist-table">
        <table>
          <thead>
            <tr>
              <th>{text(language, "Dokument", "Document")}</th>
              <th>Pipeline</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                aria-selected={item.document_id === selectedDocumentId}
                className={`clickable-row${item.document_id === selectedDocumentId ? " selected" : ""}`}
                key={item.document_id}
                onClick={() => selectItem(item.document_id)}
                onKeyDown={(event) => handleRowKeyDown(event, item.document_id)}
                role="button"
                tabIndex={disabled ? -1 : 0}
              >
                <td>
                  <div
                    className="row-select"
                    title={item.document_title}
                  >
                    <RowIcon item={item} />
                    <span>
                      <strong>{item.document_title}</strong>
                      <small>{statusLabel(item.status, language)} · {item.routing_target ?? text(language, "Unklar", "Unknown")}</small>
                    </span>
                  </div>
                </td>
                <td><ReferralPipelineChips pipeline={item.pipeline} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length === 0 && (
          <div className="empty-state">{text(language, "Keine Eintraege fuer diesen Filter.", "No items for this filter.")}</div>
        )}
      </div>
    </>
  );
}
