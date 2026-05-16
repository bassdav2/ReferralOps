import { Button } from "@carbon/react";
import { Launch } from "@carbon/icons-react";
import { useState } from "react";
import { api, type DocumentPage, type ReferralWorklistItem, type UserKey } from "../api/client";
import { text, type UiLanguage } from "../i18n";

type Props = {
  item: ReferralWorklistItem | null;
  pages: DocumentPage[];
  user: UserKey;
  language: UiLanguage;
};

function formatConfidence(value: number | null | undefined, language: UiLanguage) {
  if (value === null || value === undefined) return text(language, "unbekannt", "unknown");
  return `${Math.round(value * 100)}%`;
}

function ocrStatusLabel(item: ReferralWorklistItem, language: UiLanguage) {
  if (item.ocr_status === "failed") return text(language, "OCR fehlgeschlagen", "OCR failed");
  if (item.ocr_status === "low") return `${text(language, "OCR schwach", "Weak OCR")} ${formatConfidence(item.ocr_min_confidence, language)}`;
  if (item.ocr_status === "ok") return `OCR ok ${formatConfidence(item.ocr_min_confidence, language)}`;
  return "PDF-Text";
}

function pageTextSourceLabel(page: DocumentPage, language: UiLanguage) {
  if (page.ocr_confidence === null || page.ocr_confidence === undefined) return "PDF-Text";
  return `Tesseract ${formatConfidence(page.ocr_confidence, language)}`;
}

export function ReferralDocumentPane({ item, pages, user, language }: Props) {
  const [openError, setOpenError] = useState("");
  const [opening, setOpening] = useState(false);

  async function openOriginalPdf(documentId: string) {
    setOpenError("");
    setOpening(true);
    const viewer = window.open("", "_blank");
    if (!viewer) {
      setOpening(false);
      setOpenError(text(language, "Popup blockiert. Bitte Popups fuer localhost erlauben.", "Popup blocked. Please allow popups for localhost."));
      return;
    }
    try {
      viewer.document.title = text(language, "Original-PDF wird geladen", "Loading original PDF");
      viewer.document.body.textContent = text(language, "Original-PDF wird geladen...", "Loading original PDF...");
      const blob = await api.documentFile(documentId, user);
      const url = URL.createObjectURL(blob);
      viewer.location.href = url;
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (error) {
      viewer.close();
      setOpenError(error instanceof Error ? error.message : text(language, "Original-PDF konnte nicht geoeffnet werden", "Could not open original PDF"));
    } finally {
      setOpening(false);
    }
  }

  if (!item) {
    return (
      <>
        <div className="pane-header">
          <h2>{text(language, "Dokument", "Document")}</h2>
        </div>
        <div className="pane-body">
          <div className="empty-state">{text(language, "Kein Dokument in der Arbeitsliste ausgewaehlt.", "No document selected from the worklist.")}</div>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="pane-header document-head">
        <div>
          <span className="eyebrow">{item.source_system}</span>
          <h2>{item.document_title}</h2>
        </div>
        <div className="document-head-actions">
          <Button
            disabled={opening}
            kind="tertiary"
            renderIcon={Launch}
            size="sm"
            type="button"
            onClick={() => openOriginalPdf(item.document_id)}
          >
            {text(language, "Original-PDF oeffnen", "Open original PDF")}
          </Button>
          <span className={`mini-badge ocr-${item.ocr_status}`}>{ocrStatusLabel(item, language)}</span>
        </div>
      </div>
      {openError && <div className="message-line warning">{openError}</div>}
      <div className="paper-preview">
        {pages.length === 0 ? (
          <div className="empty-state">{text(language, "Keine Dokumentseiten geladen", "No document pages loaded")}</div>
        ) : (
          pages.map((page) => (
            <article key={page.page_number}>
              <div className="page-title">
                <strong>{text(language, "Seite", "Page")} {page.page_number}</strong>
                <span>{pageTextSourceLabel(page, language)}</span>
              </div>
              <pre>{page.text || text(language, "Keine lesbaren Zeichen auf dieser Seite.", "No readable characters on this page.")}</pre>
            </article>
          ))
        )}
      </div>
    </>
  );
}
