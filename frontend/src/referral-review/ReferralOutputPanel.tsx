import { Tag, Tile } from "@carbon/react";
import { DocumentExport } from "@carbon/icons-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ReferralDemoOutput, type UserKey } from "../api/client";
import { text, type UiLanguage } from "../i18n";

type Props = {
  user: UserKey;
  refreshToken: number;
  language: UiLanguage;
};

const DECISION_LABELS: Record<string, { de: string; en: string }> = {
  confirm: { de: "Freigeben", en: "Approved" },
  correct: { de: "Korrigieren", en: "Corrected" },
  question: { de: "Rueckfrage", en: "Question" },
  reject: { de: "Ablehnen", en: "Rejected" },
  writeback: { de: "Weitergeleitet", en: "Forwarded" }
};

function decisionTagType(decision: string) {
  if (decision === "question") return "warm-gray";
  if (decision === "reject") return "red";
  return "green";
}

function decisionLabel(output: ReferralDemoOutput, language: UiLanguage) {
  const labels = DECISION_LABELS[output.decision];
  if (labels) return text(language, labels.de, labels.en);
  return output.decision_label ?? output.decision;
}

function destinationText(output: ReferralDemoOutput, language: UiLanguage) {
  const title = output.document_title ? `${output.document_title}: ` : "";
  if (output.decision === "writeback") {
    return output.department
      ? text(language, `${title}an ${output.department} weitergeleitet`, `${title}forwarded to ${output.department}`)
      : text(language, `${title}an ${output.routing_target ?? "Zielabteilung"} weitergeleitet`, `${title}forwarded to ${output.routing_target ?? "target department"}`);
  }
  if (output.decision === "question") {
    return output.referring_organization || output.referring_physician
      ? text(language, `${title}Rueckfrage an ${output.referring_organization ?? output.referring_physician}`, `${title}question to ${output.referring_organization ?? output.referring_physician}`)
      : text(language, `${title}Rueckfrage an Zuweiser`, `${title}question to referrer`);
  }
  if (output.decision === "reject") return text(language, `${title}in Ablehnungen abgelegt`, `${title}placed in rejections`);
  if (output.decision === "confirm") return text(language, `${title}freigegeben, bereit zum Weiterleiten`, `${title}approved, ready to forward`);
  if (output.decision === "correct") return text(language, `${title}korrigiert, bereit zum Weiterleiten`, `${title}corrected, ready to forward`);
  return output.routing_target ?? text(language, "Ausgang", "Outbox");
}

function folderText(output: ReferralDemoOutput, language: UiLanguage) {
  const [folder] = output.relative_path.split("/");
  return text(language, `Ordner: ${folder || "output"} | Datei: ${output.file_name}`, `Folder: ${folder || "output"} | File: ${output.file_name}`);
}

export function ReferralOutputPanel({ user, refreshToken, language }: Props) {
  const [outputs, setOutputs] = useState<ReferralDemoOutput[]>([]);
  const [error, setError] = useState("");
  const pollFailuresRef = useRef(0);

  const loadOutputs = useCallback(async (options: { background?: boolean } = {}) => {
    try {
      const nextOutputs = await api.demoOutputs(user, 20);
      setOutputs(nextOutputs);
      setError("");
      pollFailuresRef.current = 0;
    } catch (loadError) {
      if (options.background) {
        pollFailuresRef.current += 1;
        if (pollFailuresRef.current >= 3) {
          setError((current) =>
            current || (loadError instanceof Error ? loadError.message : text(language, "Demo-Outputs konnten nicht geladen werden", "Could not load demo outputs"))
          );
        }
        return;
      }
      throw loadError;
    }
  }, [language, user]);

  useEffect(() => {
    loadOutputs().catch((loadError) => {
      setError(loadError instanceof Error ? loadError.message : text(language, "Demo-Outputs konnten nicht geladen werden", "Could not load demo outputs"));
    });
    const timer = window.setInterval(() => {
      loadOutputs({ background: true }).catch((loadError) => {
        setError(loadError instanceof Error ? loadError.message : text(language, "Demo-Outputs konnten nicht geladen werden", "Could not load demo outputs"));
      });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [loadOutputs]);

  useEffect(() => {
    loadOutputs().catch((loadError) => {
      setError(loadError instanceof Error ? loadError.message : text(language, "Demo-Outputs konnten nicht geladen werden", "Could not load demo outputs"));
    });
  }, [loadOutputs, refreshToken]);

  return (
    <section className="output-panel">
      <div className="panel-head">
        <div>
          <span className="eyebrow">Demo-Output</span>
          <h2>{text(language, "Ausgangskorb", "Outbox")}</h2>
        </div>
        <DocumentExport size={20} />
      </div>
      <p className="panel-note">
        {text(language, "Demo-Writeback: lokale JSON-Datei, keine echte KIS/DMS-Uebergabe.", "Demo handoff: local JSON file, no real EHR/DMS integration.")}
      </p>
      <div className="output-list">
        {outputs.length === 0 ? (
          <div className="empty-state small-empty">
            {text(language, "Noch kein Demo-Output geschrieben.", "No demo output written yet.")}
          </div>
        ) : (
          outputs.map((output) => (
            <Tile className="output-row" key={output.relative_path}>
              <Tag size="sm" type={decisionTagType(output.decision)}>
                {decisionLabel(output, language)}
              </Tag>
              <strong>{destinationText(output, language)}</strong>
              <small>{folderText(output, language)}</small>
            </Tile>
          ))
        )}
      </div>
      {error && <div className="message-line">{error}</div>}
    </section>
  );
}
