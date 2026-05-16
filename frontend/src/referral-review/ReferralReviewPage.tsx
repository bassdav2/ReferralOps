import { Button, InlineLoading } from "@carbon/react";
import { DocumentImport, Renew } from "@carbon/icons-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type DocumentPage,
  type ReferralBatchSummary,
  type ReferralCase,
  type ReferralRoutingTarget,
  type ReferralWorklistFilter,
  type ReferralWorklistItem,
  type UserKey
} from "../api/client";
import { text, type UiLanguage } from "../i18n";
import { ReferralAnalysisPane, type CorrectionDraft } from "./ReferralAnalysisPane";
import { ReferralBatchSummaryCards } from "./ReferralBatchSummaryCards";
import { ReferralDocumentPane } from "./ReferralDocumentPane";
import { ReferralInboxPipelinePanel } from "./ReferralInboxPipelinePanel";
import { LocalModelPanel } from "./LocalModelPanel";
import { ReferralOutputPanel } from "./ReferralOutputPanel";
import { ReferralWorklistTable } from "./ReferralWorklistTable";

type Props = {
  user: UserKey;
  language: UiLanguage;
  onHealthRefresh?: () => void;
};

type ReviewDecision = "confirm" | "correct" | "reject" | "question";

const EMPTY_CORRECTION_DRAFT: CorrectionDraft = {
  patientName: "",
  birthDate: "",
  phone: "",
  insuranceId: "",
  referringPhysician: "",
  referringOrganization: "",
  reasonForReferral: "",
  routingTarget: "",
  comment: ""
};

function draftFromCase(referralCase: ReferralCase | null): CorrectionDraft {
  if (!referralCase) return EMPTY_CORRECTION_DRAFT;
  const analysis = referralCase.analysis;
  return {
    patientName: analysis.patient.name ?? "",
    birthDate: analysis.patient.birth_date ?? "",
    phone: analysis.patient.phone ?? "",
    insuranceId: analysis.patient.insurance_id ?? "",
    referringPhysician: analysis.referring_party.physician_name ?? "",
    referringOrganization: analysis.referring_party.organization ?? "",
    reasonForReferral: analysis.clinical_context_for_admin_routing.reason_for_referral ?? "",
    routingTarget: analysis.routing_proposal.routing_target ?? "",
    comment: ""
  };
}

function emptyToNull(value: string) {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function busyActionLabel(action: string | null, language: UiLanguage) {
  if (!action) return "";
  if (action === "queue") return text(language, "Arbeitskorb wird aktualisiert", "Refreshing worklist");
  if (action === "analyze") return text(language, "Analyse laeuft", "Analysis running");
  if (action === "writeback") return text(language, "Weiterleitung wird vorbereitet", "Preparing handoff");
  if (action === "ingest-demo") return text(language, "Demo-Inbox wird eingelesen", "Reading demo inbox");
  if (action === "upload-inbox") return text(language, "PDFs werden in die Inbox gelegt", "Uploading PDFs to inbox");
  if (action === "process-inbox") return text(language, "PDF-Inbox wird verarbeitet", "Processing PDF inbox");
  if (action === "reset-demo") return text(language, "Demo-Dashboard wird zurueckgesetzt", "Resetting demo dashboard");
  if (action.startsWith("review-")) return text(language, "Review wird gespeichert", "Saving review");
  return text(language, "Wird geladen", "Loading");
}

export function ReferralReviewPage({ user, language, onHealthRefresh }: Props) {
  const [items, setItems] = useState<ReferralWorklistItem[]>([]);
  const [summary, setSummary] = useState<ReferralBatchSummary | null>(null);
  const [filter, setFilter] = useState<ReferralWorklistFilter>("active");
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [pages, setPages] = useState<DocumentPage[]>([]);
  const [currentCase, setCurrentCase] = useState<ReferralCase | null>(null);
  const [correctionDraft, setCorrectionDraft] = useState<CorrectionDraft>(EMPTY_CORRECTION_DRAFT);
  const [routingTargets, setRoutingTargets] = useState<ReferralRoutingTarget[]>([]);
  const [panelRefreshToken, setPanelRefreshToken] = useState(0);
  const [message, setMessage] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [inboxBusyAction, setInboxBusyAction] = useState<"process-inbox" | "upload-inbox" | "reset-demo" | null>(null);
  const [reanalyzingDocumentId, setReanalyzingDocumentId] = useState<string | null>(null);
  const [selectionLoadingDocumentId, setSelectionLoadingDocumentId] = useState<string | null>(null);
  const [loadedDocumentId, setLoadedDocumentId] = useState("");
  const selectedDocumentIdRef = useRef("");

  const selectedItem = useMemo(
    () => items.find((item) => item.document_id === selectedDocumentId) ?? null,
    [items, selectedDocumentId]
  );
  const loadedItem = useMemo(
    () => items.find((item) => item.document_id === loadedDocumentId) ?? null,
    [items, loadedDocumentId]
  );
  const selectionLoading = selectionLoadingDocumentId === selectedItem?.document_id;
  const visibleItem = selectionLoading && loadedItem ? loadedItem : selectedItem;
  const isResetting = inboxBusyAction === "reset-demo";
  const actionDisabled = busyAction !== null || selectionLoading || isResetting;
  const reanalyzeDisabled = reanalyzingDocumentId !== null || selectionLoading || isResetting;
  const worklistDisabled = ["queue", "ingest-demo"].includes(busyAction ?? "") || isResetting;
  const actionLoadingMessage = reanalyzingDocumentId
    ? busyActionLabel("analyze", language)
    : busyActionLabel(busyAction, language);

  function refreshPanels() {
    setPanelRefreshToken((value) => value + 1);
  }

  async function refreshQueue(
    preferredDocumentId = selectedDocumentId,
    nextFilter = filter,
    options: { showBusy?: boolean } = {}
  ) {
    const showBusy = options.showBusy ?? true;
    if (showBusy) setBusyAction("queue");
    try {
      const [rows, nextSummary] = await Promise.all([
        api.referralCases(user, nextFilter),
        api.referralBatchSummary(user)
      ]);
      setItems(rows);
      setSummary(nextSummary);
      const nextSelected = rows.some((item) => item.document_id === preferredDocumentId)
        ? preferredDocumentId
        : rows[0]?.document_id ?? "";
      setSelectedDocumentId(nextSelected);
      setMessage("");
      return rows;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Arbeitsliste konnte nicht geladen werden");
      setItems([]);
      setSummary(null);
      setSelectedDocumentId("");
      return [];
    } finally {
      if (showBusy) setBusyAction(null);
    }
  }

  useEffect(() => {
    setItems([]);
    setSummary(null);
    setSelectedDocumentId("");
    setPages([]);
    setCurrentCase(null);
    setCorrectionDraft(EMPTY_CORRECTION_DRAFT);
    setSelectionLoadingDocumentId(null);
    setLoadedDocumentId("");
    setMessage("");
    refreshQueue("", filter).catch((error) => setMessage(error.message));
  }, [user, filter]);

  useEffect(() => {
    selectedDocumentIdRef.current = selectedDocumentId;
  }, [selectedDocumentId]);

  useEffect(() => {
    api.routingTargets(user)
      .then(setRoutingTargets)
      .catch(() => setRoutingTargets([]));
  }, [user]);

  useEffect(() => {
    if (inboxBusyAction !== "process-inbox") return;
    const timer = window.setInterval(() => {
      refreshQueue(selectedDocumentIdRef.current, "active", { showBusy: false }).catch((error) => {
        setMessage(error instanceof Error ? error.message : "Arbeitsliste konnte nicht aktualisiert werden");
      });
      refreshPanels();
    }, 1500);
    return () => window.clearInterval(timer);
  }, [inboxBusyAction, user]);

  useEffect(() => {
    if (!selectedItem) {
      setPages([]);
      setCurrentCase(null);
      setCorrectionDraft(EMPTY_CORRECTION_DRAFT);
      setSelectionLoadingDocumentId(null);
      setLoadedDocumentId("");
      return;
    }
    let cancelled = false;
    setSelectionLoadingDocumentId(selectedItem.document_id);
    Promise.all([
      api.documentPages(selectedItem.document_id, user),
      selectedItem.case_id ? api.getReferralCase(selectedItem.case_id, user) : Promise.resolve(null)
    ])
      .then(([nextPages, nextCase]) => {
        if (cancelled) return;
        setPages(nextPages);
        setCurrentCase(nextCase);
        setCorrectionDraft(draftFromCase(nextCase));
        setLoadedDocumentId(selectedItem.document_id);
        setMessage("");
      })
      .catch((error) => {
        if (cancelled) return;
        setMessage(error instanceof Error ? error.message : "Dokument konnte nicht geladen werden");
        setPages([]);
        setCurrentCase(null);
        setCorrectionDraft(EMPTY_CORRECTION_DRAFT);
        setLoadedDocumentId(selectedItem.document_id);
      })
      .finally(() => {
        if (!cancelled) {
          setSelectionLoadingDocumentId((current) =>
            current === selectedItem.document_id ? null : current
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedItem?.document_id, selectedItem?.case_id, user]);

  async function analyze() {
    if (!selectedItem || reanalyzingDocumentId !== null) return;
    const documentId = selectedItem.document_id;
    setReanalyzingDocumentId(documentId);
    try {
      setMessage("Analyse laeuft");
      const result = await api.analyzeReferral(documentId, user);
      if (selectedDocumentIdRef.current === documentId) {
        setCurrentCase(result);
        setCorrectionDraft(draftFromCase(result));
      }
      setFilter("active");
      await refreshQueue(selectedDocumentIdRef.current || documentId, "active", { showBusy: false });
      refreshPanels();
      setMessage("Analyse gespeichert");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Analyse fehlgeschlagen");
    } finally {
      setReanalyzingDocumentId((current) => current === documentId ? null : current);
    }
  }

  async function review(decision: ReviewDecision) {
    if (!currentCase) return;
    const selectedRoutingTarget = routingTargets.find((target) => target.routing_target === correctionDraft.routingTarget);
    if (decision === "correct" && !selectedRoutingTarget) {
      setMessage("Bitte eine gueltige Zielroute waehlen, bevor die Korrektur freigegeben wird.");
      return;
    }
    const corrected = decision === "correct" && selectedRoutingTarget
      ? {
          ...currentCase.analysis,
          patient: {
            ...currentCase.analysis.patient,
            name: emptyToNull(correctionDraft.patientName),
            birth_date: emptyToNull(correctionDraft.birthDate),
            phone: emptyToNull(correctionDraft.phone),
            insurance_id: emptyToNull(correctionDraft.insuranceId)
          },
          referring_party: {
            ...currentCase.analysis.referring_party,
            physician_name: emptyToNull(correctionDraft.referringPhysician),
            organization: emptyToNull(correctionDraft.referringOrganization)
          },
          clinical_context_for_admin_routing: {
            ...currentCase.analysis.clinical_context_for_admin_routing,
            reason_for_referral: emptyToNull(correctionDraft.reasonForReferral)
          },
          routing_proposal: {
            ...currentCase.analysis.routing_proposal,
            routing_target: selectedRoutingTarget.routing_target,
            department: selectedRoutingTarget.department
          }
        }
      : null;
    const comment = emptyToNull(correctionDraft.comment)
      ?? (decision === "correct" ? "Demo correction from UI" : null);
    setBusyAction(`review-${decision}`);
    try {
      await api.reviewReferral(currentCase.id, decision, corrected, user, comment);
      const refreshed = await api.getReferralCase(currentCase.id, user);
      setCurrentCase(refreshed);
      setCorrectionDraft(draftFromCase(refreshed));
      await refreshQueue(refreshed.document_id, filter, { showBusy: false });
      refreshPanels();
      setMessage(`Review gespeichert: ${decision}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Review fehlgeschlagen");
    } finally {
      setBusyAction(null);
    }
  }

  async function writeback() {
    if (!currentCase) return;
    setBusyAction("writeback");
    try {
      const result = await api.writebackReferral(currentCase.id, user);
      setFilter("active");
      await refreshQueue("", "active", { showBusy: false });
      refreshPanels();
      const path = result.path ? ` (${result.path})` : "";
      setMessage(`Weitergeleitet in den Ausgangskorb${path}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Writeback fehlgeschlagen");
    } finally {
      setBusyAction(null);
    }
  }

  async function ingestDemoInbox() {
    setBusyAction("ingest-demo");
    try {
      const result = await api.ingestReferralDemoSources(user);
      await refreshQueue(selectedDocumentId, filter, { showBusy: false });
      refreshPanels();
      setMessage(
        `Demo-Inbox: ${result.documents} neu, ${result.changed} geaendert, ${result.skipped} unveraendert, ${result.analyses} analysiert`
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Demo-Inbox konnte nicht eingelesen werden");
    } finally {
      setBusyAction(null);
    }
  }

  async function processInbox(limit: number) {
    setInboxBusyAction("process-inbox");
    try {
      setFilter("active");
      setMessage(`${limit} PDF${limit === 1 ? "" : "s"} werden aus der PDF-Inbox verarbeitet`);
      refreshPanels();
      const result = await api.processReferralInbox(user, limit);
      setSummary(result.summary);
      const preferredDocumentId = selectedDocumentIdRef.current || result.documents[0]?.document_id || selectedDocumentId;
      await refreshQueue(preferredDocumentId, "active", { showBusy: false });
      refreshPanels();
      setMessage(
        `Pipeline abgeschlossen: ${result.processed} verarbeitet, ${result.inbox.processable_pdfs} weiter verarbeitbar`
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "PDF-Pipeline fehlgeschlagen");
    } finally {
      setInboxBusyAction(null);
    }
  }

  async function uploadInbox(files: File[]) {
    setInboxBusyAction("upload-inbox");
    try {
      const result = await api.uploadReferralInbox(user, files);
      await refreshQueue(selectedDocumentId, filter, { showBusy: false });
      refreshPanels();
      const rejected = result.rejected.length > 0
        ? `, ${result.rejected.length} abgelehnt`
        : "";
      setMessage(`${result.uploaded} PDF${result.uploaded === 1 ? "" : "s"} in die Inbox gelegt${rejected}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "PDF-Upload fehlgeschlagen");
      throw error;
    } finally {
      setInboxBusyAction(null);
    }
  }

  async function resetDemoDashboard() {
    const confirmed = window.confirm(
      "Demo-Dashboard wirklich zuruecksetzen? Dadurch werden Arbeitskorb, PDF-Inbox, Pipeline-Events und Demo-Outputs geleert."
    );
    if (!confirmed) return;
    setInboxBusyAction("reset-demo");
    try {
      const result = await api.resetReferralDemo(user);
      setItems([]);
      setSummary(result.summary);
      setFilter("active");
      setSelectedDocumentId("");
      setPages([]);
      setCurrentCase(null);
      setCorrectionDraft(EMPTY_CORRECTION_DRAFT);
      setSelectionLoadingDocumentId(null);
      setLoadedDocumentId("");
      refreshPanels();
      setMessage(
        `Demo zurueckgesetzt: ${result.documents_deleted} Dokumente, ${result.inbox_files_deleted} Inbox-PDFs, ${result.output_files_deleted} Outputs geloescht`
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Demo-Reset fehlgeschlagen");
    } finally {
      setInboxBusyAction(null);
    }
  }

  return (
    <section className="module referral-module">
      <div className="module-header">
        <div>
          <h1>{text(language, "Zuweisungs-Arbeitskorb", "Referral Worklist")}</h1>
          <p>
            {text(
              language,
              "Zentrale Eingangsstelle fuer Pruefung, Rueckfrage und Weiterleitung.",
              "Central intake desk for review, questions, and forwarding."
            )}
          </p>
        </div>
        <div className="button-row">
          {user === "it_admin" && (
            <Button
              title={text(language, "Demo-Inbox einlesen", "Read demo inbox")}
              onClick={ingestDemoInbox}
              disabled={busyAction !== null || inboxBusyAction !== null}
              renderIcon={DocumentImport}
              size="md"
              type="button"
            >
              {text(language, "Demo-Inbox einlesen", "Read demo inbox")}
            </Button>
          )}
          <Button
            hasIconOnly
            iconDescription={text(language, "Arbeitskorb aktualisieren", "Refresh worklist")}
            kind="ghost"
            title={text(language, "Arbeitskorb aktualisieren", "Refresh worklist")}
            onClick={() => refreshQueue()}
            disabled={busyAction !== null || isResetting}
            renderIcon={Renew}
            size="md"
            type="button"
          />
        </div>
      </div>

      {actionLoadingMessage && (
        <div className="module-loading-toast">
          <InlineLoading status="active" description={actionLoadingMessage} />
        </div>
      )}

      <ReferralBatchSummaryCards summary={summary} language={language} />

      {user === "it_admin" && (
        <LocalModelPanel user={user} language={language} onHealthRefresh={onHealthRefresh} />
      )}

      <ReferralInboxPipelinePanel
        user={user}
        refreshToken={panelRefreshToken}
        items={items}
        language={language}
        disabled={busyAction !== null || isResetting}
        processing={inboxBusyAction === "process-inbox"}
        uploading={inboxBusyAction === "upload-inbox"}
        resetting={inboxBusyAction === "reset-demo"}
        canReset={user === "it_admin"}
        onProcess={processInbox}
        onUpload={uploadInbox}
        onReset={resetDemoDashboard}
      />

      <div className="referral-workspace">
        <section className="queue-pane">
          <ReferralWorklistTable
            items={items}
            filter={filter}
            selectedDocumentId={selectedDocumentId}
            language={language}
            disabled={worklistDisabled}
            onFilterChange={setFilter}
            onSelect={(documentId) => {
              setSelectedDocumentId(documentId);
            }}
          />
        </section>

        <section className={`document-pane${selectionLoading ? " pane-is-loading" : ""}`}>
          <ReferralDocumentPane item={visibleItem} pages={pages} user={user} language={language} />
          {selectionLoading && (
            <div className="pane-loading-overlay">
              <InlineLoading
                status="active"
                description={selectedItem?.document_title
                  ? `Lade ${selectedItem.document_title}`
                  : "Dokument wird geladen"}
              />
            </div>
          )}
        </section>

        <section className={`analysis-pane${selectionLoading ? " pane-is-loading" : ""}`}>
          <ReferralAnalysisPane
            item={visibleItem}
            currentCase={currentCase}
            correctionDraft={correctionDraft}
            routingTargets={routingTargets}
            language={language}
            loading={selectionLoading}
            disabled={actionDisabled}
            reanalyzeDisabled={reanalyzeDisabled}
            onAnalyze={analyze}
            onReview={review}
            onWriteback={writeback}
            onCorrectionDraftChange={(field, value) =>
              setCorrectionDraft((draft) => ({ ...draft, [field]: value }))
            }
          />
          {selectionLoading && currentCase && (
            <div className="pane-loading-overlay">
              <InlineLoading
                status="active"
                description={selectedItem?.document_title
                  ? `Lade Analyse ${selectedItem.document_title}`
                  : "Analyse wird geladen"}
              />
            </div>
          )}
          {message && <div className="message-line">{message}</div>}
        </section>
      </div>

      <div className="referral-demo-panels">
        <ReferralOutputPanel user={user} refreshToken={panelRefreshToken} language={language} />
      </div>
    </section>
  );
}
