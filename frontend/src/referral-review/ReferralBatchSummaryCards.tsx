import { Tag, Tile } from "@carbon/react";
import type { ReferralBatchSummary } from "../api/client";
import { text, type UiLanguage } from "../i18n";

type Props = {
  summary: ReferralBatchSummary | null;
  language: UiLanguage;
};

const EMPTY = "-";

export function ReferralBatchSummaryCards({ summary, language }: Props) {
  const readyToForwardCount = summary
    ? summary.ready_to_forward ?? summary.confirmed + summary.corrected
    : null;
  const forwardedCount = summary ? summary.forwarded ?? 0 : null;
  const activeWorklist = summary && forwardedCount !== null
    ? summary.active_worklist ?? Math.max(0, summary.total_documents - forwardedCount - summary.questions - summary.rejected)
    : EMPTY;
  const openItems = summary && readyToForwardCount !== null && forwardedCount !== null
    ? summary.open_items ?? Math.max(0, summary.total_documents - readyToForwardCount - forwardedCount - summary.questions - summary.rejected)
    : EMPTY;
  const cards = [
    { label: text(language, "Arbeitskorb", "Worklist"), value: activeWorklist },
    { label: text(language, "Offen", "Open"), value: openItems, tone: "warn" },
    { label: text(language, "Freigegeben", "Approved"), value: readyToForwardCount ?? EMPTY },
    { label: text(language, "Weitergeleitet", "Forwarded"), value: forwardedCount ?? EMPTY },
    { label: text(language, "Rueckfragen", "Questions"), value: summary?.questions ?? EMPTY, tone: "warn" },
    { label: text(language, "Abgelehnt", "Rejected"), value: summary?.rejected ?? EMPTY, tone: "danger" }
  ];

  return (
    <div className="summary-strip">
      {cards.map((card) => (
        <Tile className={`summary-tile ${card.tone ?? ""}`} key={card.label}>
          <Tag size="sm" type={card.tone === "danger" ? "red" : card.tone === "warn" ? "warm-gray" : "gray"}>
            {card.label}
          </Tag>
          <strong>{card.value}</strong>
        </Tile>
      ))}
    </div>
  );
}
