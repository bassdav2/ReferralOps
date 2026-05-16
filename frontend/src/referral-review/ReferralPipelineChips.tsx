import { Tag } from "@carbon/react";
import { CheckmarkFilled, CloseFilled, Time, WarningAltFilled } from "@carbon/icons-react";
import type { ReferralPipelineStageStatus, ReferralWorklistPipelineStatus } from "../api/client";

const STAGE_ORDER: Array<keyof ReferralWorklistPipelineStatus> = [
  "inbox",
  "pypdf",
  "ocr",
  "model",
  "review",
  "output"
];

const FALLBACK_PIPELINE: ReferralWorklistPipelineStatus = {
  inbox: { status: "unknown", label: "Inbox", detail: "Backend response has no pipeline status yet" },
  pypdf: { status: "unknown", label: "PyPDF", detail: "Backend response has no pipeline status yet" },
  ocr: { status: "unknown", label: "OCR", detail: "Backend response has no pipeline status yet" },
  model: { status: "unknown", label: "Gemma", detail: "Backend response has no pipeline status yet" },
  review: { status: "unknown", label: "Review", detail: "Backend response has no pipeline status yet" },
  output: { status: "unknown", label: "Output", detail: "Backend response has no pipeline status yet" }
};

function tagType(stage: ReferralPipelineStageStatus) {
  if (stage.status === "failed") return "red";
  if (stage.status === "warning") return "warm-gray";
  if (stage.status === "ok" || stage.status === "completed") return "green";
  return "gray";
}

function statusIcon(stage: ReferralPipelineStageStatus) {
  if (stage.status === "failed") return CloseFilled;
  if (stage.status === "warning") return WarningAltFilled;
  if (stage.status === "ok" || stage.status === "completed") return CheckmarkFilled;
  return Time;
}

export function ReferralPipelineChips({ pipeline }: { pipeline?: ReferralWorklistPipelineStatus }) {
  const safePipeline = pipeline ?? FALLBACK_PIPELINE;
  return (
    <div className="pipeline-chips" aria-label="Referral pipeline status">
      {STAGE_ORDER.map((stageKey) => {
        const stage = safePipeline[stageKey] ?? FALLBACK_PIPELINE[stageKey];
        return (
          <Tag
            className={`pipeline-chip status-${stage.status}`}
            renderIcon={statusIcon(stage)}
            size="sm"
            title={stage.detail ?? stage.label}
            type={tagType(stage)}
            key={stageKey}
          >
            {stage.label}
          </Tag>
        );
      })}
    </div>
  );
}
