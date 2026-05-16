import { Button, InlineLoading, Select, SelectItem, Tag } from "@carbon/react";
import {
  CheckmarkFilled,
  CloudUpload,
  DataCheck,
  DocumentImport,
  Renew,
  Time,
  WarningAltFilled
} from "@carbon/icons-react";
import { type DragEvent as ReactDragEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type ReferralInboxSummary,
  type ReferralPipelineEvent,
  type ReferralWorklistItem,
  type UserKey
} from "../api/client";
import { text, type UiLanguage } from "../i18n";

type Props = {
  user: UserKey;
  refreshToken: number;
  items: ReferralWorklistItem[];
  language: UiLanguage;
  disabled: boolean;
  processing: boolean;
  uploading: boolean;
  resetting: boolean;
  canReset: boolean;
  onProcess: (limit: number) => Promise<void>;
  onUpload: (files: File[]) => Promise<void>;
  onReset: () => Promise<void>;
};

type StageKey = "inbox" | "pypdf" | "ocr" | "model" | "validation" | "worklist" | "output";
type StageState = "pending" | "active" | "complete" | "warning" | "failed";

const STAGES: Array<{ key: StageKey; de: string; en: string; eventStages: string[] }> = [
  { key: "inbox", de: "Inbox", en: "Inbox", eventStages: ["inbox"] },
  { key: "pypdf", de: "PyPDF", en: "PyPDF", eventStages: ["pypdf"] },
  { key: "ocr", de: "OCR", en: "OCR", eventStages: ["ocr"] },
  { key: "model", de: "Local Model", en: "Local Model", eventStages: ["model"] },
  { key: "validation", de: "Validierung", en: "Validation", eventStages: ["validation"] },
  { key: "worklist", de: "Arbeitskorb", en: "Worklist", eventStages: ["worklist"] },
  { key: "output", de: "Output", en: "Output", eventStages: ["output", "writeback"] }
];
const CLIENT_UPLOAD_MAX_BYTES = 20 * 1024 * 1024;

function eventState(event: ReferralPipelineEvent | null): StageState {
  if (!event) return "pending";
  if (event.status === "started") return "active";
  if (event.status === "failed") return "failed";
  if (event.status === "warning") return "warning";
  return "complete";
}

function stageIcon(state: StageState) {
  if (state === "failed" || state === "warning") return WarningAltFilled;
  if (state === "complete") return CheckmarkFilled;
  if (state === "active") return DataCheck;
  return Time;
}

function stageLabel(stage: { key: StageKey; de: string; en: string }, event: ReferralPipelineEvent | null, language: UiLanguage) {
  if (stage.key === "ocr" && event?.payload && typeof event.payload.ocr_min_confidence === "number") {
    return `OCR ${Math.round(event.payload.ocr_min_confidence * 100)}%`;
  }
  return text(language, stage.de, stage.en);
}

function titleFromEvents(events: ReferralPipelineEvent[]) {
  const inboxEvent = events.find((event) => event.stage === "inbox" && event.message.includes("PDF found"));
  if (!inboxEvent) return null;
  const parts = inboxEvent.message.split("PDF found");
  return parts[parts.length - 1]?.trim() || null;
}

function shortTitle(title: string) {
  return title.length > 42 ? `${title.slice(0, 39)}...` : title;
}

function isPipelineFinished(events: ReferralPipelineEvent[]) {
  return events.some(
    (event) =>
      (event.stage === "worklist" && event.status === "completed") ||
      ((event.stage === "output" || event.stage === "writeback") &&
        ["completed", "ok", "warning"].includes(event.status))
  );
}

function formatLocation(summary: ReferralInboxSummary | null, language: UiLanguage) {
  if (!summary) return "PDF-Inbox";
  return summary.backend === "filesystem" ? text(language, "Lokaler Ordner", "Local folder") : `${summary.bucket}/${summary.prefix}`.replace(/\/$/, "");
}

function backendLabel(summary: ReferralInboxSummary | null, language: UiLanguage) {
  if (!summary) return "Backend";
  return summary.backend === "filesystem" ? text(language, "Lokaler Ordner", "Local folder") : "MinIO";
}

function isFileDrag(event: ReactDragEvent<HTMLElement> | DragEvent) {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

function filesFromDrop(event: ReactDragEvent<HTMLElement>) {
  const transfer = event.dataTransfer;
  const itemFiles = Array.from(transfer.items ?? [])
    .filter((item) => item.kind === "file")
    .map((item) => item.getAsFile())
    .filter((file): file is File => file !== null);
  return itemFiles.length > 0 ? itemFiles : Array.from(transfer.files ?? []);
}

function friendlyLoadError(error: unknown, summary: ReferralInboxSummary | null, language: UiLanguage) {
  const message = error instanceof Error ? error.message : "";
  if (summary?.backend === "minio" || message.toLowerCase().includes("minio")) {
    return text(language, "MinIO-Inbox nicht erreichbar. Bitte MinIO starten und Bucket pruefen.", "MinIO inbox is not reachable. Start MinIO and check the bucket.");
  }
  if (message === "Failed to fetch") {
    return text(language, "Backend nicht erreichbar. Bitte Backend starten oder Verbindung pruefen.", "Backend is not reachable. Start the backend or check the connection.");
  }
  return message || text(language, "PDF-Inbox konnte nicht geladen werden", "Could not load PDF inbox");
}

export function ReferralInboxPipelinePanel({
  user,
  refreshToken,
  items,
  language,
  disabled,
  processing,
  uploading,
  resetting,
  canReset,
  onProcess,
  onUpload,
  onReset
}: Props) {
  const [summary, setSummary] = useState<ReferralInboxSummary | null>(null);
  const [events, setEvents] = useState<ReferralPipelineEvent[]>([]);
  const [limit, setLimit] = useState(2);
  const [actionError, setActionError] = useState("");
  const [connectivityError, setConnectivityError] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pollFailuresRef = useRef(0);
  const summaryRef = useRef<ReferralInboxSummary | null>(null);
  const canUpload = !disabled && !uploading && !processing && !resetting;
  const resetDisabled = disabled || processing || uploading || resetting || !canReset;
  const resetTitle = canReset
    ? text(language, "Demo-Dashboard zuruecksetzen", "Reset demo dashboard")
    : text(language, "Nur IT/Admin Demo kann die Demo zuruecksetzen", "Only IT/Admin Demo can reset the demo");

  const itemTitles = useMemo(() => {
    return new Map(items.map((item) => [item.document_id, item.document_title]));
  }, [items]);

  const load = useCallback(async (options: { background?: boolean } = {}) => {
    const [summaryResult, eventsResult] = await Promise.allSettled([
      api.referralInboxSummary(user),
      api.pipelineEvents(user, { limit: 160 })
    ]);

    if (summaryResult.status === "fulfilled") {
      summaryRef.current = summaryResult.value;
      setSummary(summaryResult.value);
    }
    if (eventsResult.status === "fulfilled") {
      setEvents(eventsResult.value);
    }

    const firstFailure =
      summaryResult.status === "rejected"
        ? summaryResult.reason
        : eventsResult.status === "rejected"
          ? eventsResult.reason
          : null;

    if (!firstFailure) {
      pollFailuresRef.current = 0;
      setConnectivityError("");
      setActionError("");
      return;
    }

    if (options.background) {
      pollFailuresRef.current += 1;
      if (pollFailuresRef.current >= 3) {
        setConnectivityError((current) => current || friendlyLoadError(firstFailure, summaryRef.current, language));
      }
      return;
    }

    pollFailuresRef.current = 0;
    setActionError(friendlyLoadError(firstFailure, summaryRef.current, language));
  }, [language, user]);

  useEffect(() => {
    load().catch((loadError) => {
      setActionError(friendlyLoadError(loadError, summaryRef.current, language));
    });
    const timer = window.setInterval(() => {
      load({ background: true }).catch((loadError) => {
        pollFailuresRef.current += 1;
        if (pollFailuresRef.current >= 3) {
          setConnectivityError((current) => current || friendlyLoadError(loadError, summaryRef.current, language));
        }
      });
    }, 4000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    load().catch((loadError) => {
      setActionError(friendlyLoadError(loadError, summaryRef.current, language));
    });
  }, [load, refreshToken]);

  useEffect(() => {
    const preventFileNavigation = (event: DragEvent) => {
      if (isFileDrag(event)) {
        event.preventDefault();
      }
    };
    window.addEventListener("dragover", preventFileNavigation);
    window.addEventListener("drop", preventFileNavigation);
    return () => {
      window.removeEventListener("dragover", preventFileNavigation);
      window.removeEventListener("drop", preventFileNavigation);
    };
  }, []);

  const submitFiles = useCallback(
    async (fileList: FileList | File[]) => {
      const files = Array.from(fileList);
      if (files.length === 0) return;
      const pdfFiles = files.filter((file) => file.name.toLowerCase().endsWith(".pdf"));
      const sizeAllowedFiles = pdfFiles.filter((file) => file.size <= CLIENT_UPLOAD_MAX_BYTES);
      const rejectedCount = files.length - sizeAllowedFiles.length;
      if (rejectedCount > 0) {
        setActionError(
          text(
            language,
            `${rejectedCount} Datei(en) wurden vor dem Upload abgelehnt. Nur PDFs bis 20 MB sind erlaubt.`,
            `${rejectedCount} file(s) were rejected before upload. Only PDFs up to 20 MB are allowed.`
          )
        );
      }
      if (sizeAllowedFiles.length === 0) return;
      try {
        if (rejectedCount === 0) setActionError("");
        await onUpload(sizeAllowedFiles);
        await load();
      } catch (uploadError) {
        setActionError(uploadError instanceof Error ? uploadError.message : text(language, "Upload fehlgeschlagen", "Upload failed"));
      }
    },
    [language, load, onUpload]
  );

  const rows = useMemo(() => {
    const chronological = [...events].reverse();
    const grouped = new Map<string, ReferralPipelineEvent[]>();
    for (const event of chronological) {
      if (!event.document_id) continue;
      const current = grouped.get(event.document_id) ?? [];
      current.push(event);
      grouped.set(event.document_id, current);
    }
    return [...grouped.entries()]
      .map(([documentId, documentEvents]) => {
        if (isPipelineFinished(documentEvents)) return null;
        const latest = documentEvents[documentEvents.length - 1];
        const title = itemTitles.get(documentId) ?? titleFromEvents(documentEvents);
        if (!title) return null;
        return {
          documentId,
          title,
          latestAt: latest?.created_at ?? "",
          events: documentEvents
        };
      })
      .filter((row): row is { documentId: string; title: string; latestAt: string; events: ReferralPipelineEvent[] } => row !== null)
      .sort((left, right) => right.latestAt.localeCompare(left.latestAt))
      .slice(0, Math.max(2, Math.min(limit, 6)));
  }, [events, itemTitles, limit]);

  const processable = summary?.processable_pdfs ?? 0;

  return (
    <section className="inbox-pipeline-panel">
      <div className="inbox-pipeline-head">
        <div>
          <span className="eyebrow">PDF-Inbox</span>
          <h2>{formatLocation(summary, language)}</h2>
        </div>
        <div className="inbox-pipeline-metrics">
          <Tag size="sm" type="gray">
            {backendLabel(summary, language)}
          </Tag>
          <Tag renderIcon={CloudUpload} size="sm" type="blue">
            {summary?.total_pdfs ?? "-"} PDFs
          </Tag>
          <Tag size="sm" type={processable > 0 ? "green" : "gray"}>
            {processable} {text(language, "verarbeitbar", "processable")}
          </Tag>
          <Tag size="sm" type="gray">
            {summary?.analyzed_documents ?? "-"} {text(language, "analysiert", "analyzed")}
          </Tag>
        </div>
        <div className="inbox-pipeline-actions">
          <Select
            hideLabel
            id="referral-inbox-limit"
            labelText={text(language, "PDF-Anzahl", "PDF count")}
            size="sm"
            value={String(limit)}
            onChange={(event) => setLimit(Number(event.target.value))}
          >
            {[1, 2, 5, 10, 25, 100].map((value) => (
              <SelectItem key={value} text={`${value} PDF${value === 1 ? "" : "s"}`} value={String(value)} />
            ))}
          </Select>
          <Button
            disabled={disabled || processing || processable === 0}
            kind="primary"
            onClick={() => onProcess(limit)}
            renderIcon={DocumentImport}
            size="sm"
            type="button"
          >
            {text(language, "Neue PDFs verarbeiten", "Process new PDFs")}
          </Button>
          <Button
            disabled={resetDisabled}
            kind="danger--ghost"
            onClick={onReset}
            renderIcon={Renew}
            size="sm"
            title={resetTitle}
            type="button"
          >
            {text(language, "Demo zuruecksetzen", "Reset demo")}
          </Button>
        </div>
      </div>

      <div
        className={`inbox-upload-wrap${dragActive ? " drag-active" : ""}`}
        onDragEnter={(event) => {
          if (!isFileDrag(event)) return;
          event.preventDefault();
          event.stopPropagation();
          if (canUpload) setDragActive(true);
        }}
        onDragOver={(event) => {
          if (!isFileDrag(event)) return;
          event.preventDefault();
          event.stopPropagation();
          if (canUpload) {
            event.dataTransfer.dropEffect = "copy";
            setDragActive(true);
          }
        }}
        onDragLeave={(event) => {
          if (!isFileDrag(event)) return;
          event.preventDefault();
          event.stopPropagation();
          const relatedTarget = event.relatedTarget as Node | null;
          if (!relatedTarget || !event.currentTarget.contains(relatedTarget)) {
            setDragActive(false);
          }
        }}
        onDrop={(event) => {
          if (!isFileDrag(event)) return;
          event.preventDefault();
          event.stopPropagation();
          setDragActive(false);
          if (canUpload) {
            submitFiles(filesFromDrop(event)).catch(() => undefined);
          }
        }}
      >
        <input
          ref={fileInputRef}
          accept="application/pdf,.pdf"
          className="visually-hidden"
          multiple
          type="file"
          onChange={(event) => {
            if (event.target.files) {
              submitFiles(event.target.files).catch(() => undefined);
            }
            event.target.value = "";
          }}
        />
        <div
          aria-disabled={!canUpload}
          className={`inbox-upload-zone${dragActive ? " drag-active" : ""}${!canUpload ? " disabled" : ""}`}
          role="button"
          tabIndex={canUpload ? 0 : -1}
          onClick={() => {
            if (canUpload) fileInputRef.current?.click();
          }}
          onKeyDown={(event) => {
            if (!canUpload) return;
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              fileInputRef.current?.click();
            }
          }}
        >
          {uploading ? (
            <InlineLoading status="active" description={text(language, "PDFs werden in die Inbox gelegt", "Uploading PDFs to inbox")} />
          ) : resetting ? (
            <InlineLoading status="active" description={text(language, "Demo wird zurueckgesetzt", "Resetting demo")} />
          ) : (
            <>
              <CloudUpload size={18} />
              <span>{text(language, "PDFs hier ablegen oder auswaehlen", "Drop PDFs here or choose files")}</span>
            </>
          )}
        </div>
      </div>

      {processing && (
        <div className="inbox-pipeline-running">
          <InlineLoading status="active" description={text(language, "Pipeline verarbeitet PDF-Inbox", "Pipeline is processing the PDF inbox")} />
        </div>
      )}

      <div className="inbox-pipeline-rows">
        {rows.length === 0 ? (
          <div className="empty-state small-empty">
            {text(language, "Noch kein aktueller Pipeline-Lauf sichtbar.", "No current pipeline run visible.")}
          </div>
        ) : (
          rows.map((row) => (
            <div className="inbox-pipeline-row" key={row.documentId}>
              <strong title={row.title}>{shortTitle(row.title)}</strong>
              <div className="inbox-stage-strip">
                {STAGES.map((stage) => {
                  const stageEvents = row.events.filter((event) => stage.eventStages.includes(event.stage));
                  const latest = stageEvents[stageEvents.length - 1] ?? null;
                  const state = eventState(latest);
                  const Icon = stageIcon(state);
                  return (
                    <span className={`inbox-stage-pill state-${state}`} key={stage.key} title={latest?.message ?? text(language, stage.de, stage.en)}>
                      <Icon size={14} />
                      {stageLabel(stage, latest, language)}
                    </span>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>

      {(actionError || connectivityError) && (
        <div className="message-line warning">{actionError || connectivityError}</div>
      )}
    </section>
  );
}
