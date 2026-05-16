const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const REQUEST_TIMEOUT_MS = 30_000;
const LONG_REQUEST_TIMEOUT_MS = 1_800_000;

export type UserKey =
  | "sekretariat_kardiologie"
  | "hygiene_user"
  | "it_admin"
  | "restricted_user";

export type DocumentRead = {
  id: string;
  source_system: string;
  title: string;
  mime_type: string;
  sha256: string;
  access_groups: string[];
  contains_patient_data: boolean;
  parse_status: string;
};

export type DocumentPage = {
  page_number: number;
  text: string;
  ocr_confidence: number | null;
};

export type ReferralAnalysis = {
  document_id: string;
  document_type: string;
  language: string;
  patient: Record<string, string | null>;
  referring_party: Record<string, string | null>;
  clinical_context_for_admin_routing: {
    reason_for_referral: string | null;
    symptoms: string[];
    suspected_or_known_conditions: string[];
    medication_list_mentioned: boolean;
    lab_or_imaging_mentioned: boolean;
    requested_service: string | null;
  };
  attachments: Record<string, string>;
  routing_proposal: {
    department: string | null;
    routing_target: string | null;
    administrative_urgency: string;
    confidence: number;
  };
  missing_items: Array<{ field: string; reason: string; severity: string }>;
  evidence: Array<{ claim: string; quote: string; page: number | null }>;
  human_review_required: boolean;
  warnings: string[];
  ocr_min_confidence: number | null;
  ocr_status: "ok" | "low" | "failed" | "unknown";
};

export type ReferralCase = {
  id: string;
  document_id: string;
  status: string;
  analysis: ReferralAnalysis;
  model_profile: string;
  prompt_version: string;
  created_at: string;
  reviewed_at: string | null;
};

export type ReferralWorklistFilter =
  | "active"
  | "all"
  | "new"
  | "review_required"
  | "ocr_low"
  | "route_unclear"
  | "confirmed"
  | "rejected";

export type ReferralPipelineStageStatus = {
  status: "ok" | "warning" | "failed" | "pending" | "completed" | "unknown";
  label: string;
  detail: string | null;
};

export type ReferralWorklistPipelineStatus = {
  inbox: ReferralPipelineStageStatus;
  pypdf: ReferralPipelineStageStatus;
  ocr: ReferralPipelineStageStatus;
  model: ReferralPipelineStageStatus;
  review: ReferralPipelineStageStatus;
  output: ReferralPipelineStageStatus;
};

export type ReferralWorklistItem = {
  case_id: string | null;
  document_id: string;
  document_title: string;
  source_system: string;
  status: string;
  routing_target: string | null;
  department: string | null;
  confidence: number | null;
  human_review_required: boolean;
  missing_count: number;
  ocr_min_confidence: number | null;
  ocr_status: "ok" | "low" | "failed" | "unknown";
  warnings: string[];
  created_at: string;
  reviewed_at: string | null;
  pipeline: ReferralWorklistPipelineStatus;
};

export type ReferralPipelineEvent = {
  id: string;
  document_id: string | null;
  case_id: string | null;
  stage: string;
  status: string;
  message: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};

export type ReferralDemoOutput = {
  decision: string;
  decision_label: string | null;
  file_name: string;
  relative_path: string;
  case_id: string | null;
  document_id: string | null;
  document_title: string | null;
  department: string | null;
  routing_target: string | null;
  referring_organization: string | null;
  referring_physician: string | null;
  created_at: string | null;
};

export type ReferralWritebackResult = {
  status: string;
  message?: string;
  path?: string;
  extra_paths?: string[];
  case_id?: string;
};

export type ReferralRoutingTarget = {
  routing_target: string;
  department: string;
};

export type MissingFieldCount = {
  field: string;
  count: number;
};

export type ReferralBatchSummary = {
  total_documents: number;
  active_worklist: number;
  open_items: number;
  new_documents: number;
  analyzed: number;
  review_required: number;
  ready_to_forward: number;
  forwarded: number;
  ocr_low: number;
  ocr_failed: number;
  route_unclear: number;
  model_errors: number;
  confirmed: number;
  corrected: number;
  rejected: number;
  questions: number;
  routing_distribution: Record<string, number>;
  top_missing_fields: MissingFieldCount[];
  average_confidence: number | null;
  average_ocr_confidence: number | null;
  generated_at: string;
};

export type ReferralIngestReport = {
  documents: number;
  skipped: number;
  changed: number;
  analyses: number;
  summary: ReferralBatchSummary;
};

export type ReferralInboxSummary = {
  source_name: string;
  backend: "filesystem" | "minio";
  location: string;
  bucket: string;
  prefix: string;
  total_pdfs: number;
  registered_documents: number;
  unregistered_pdfs: number;
  analyzed_documents: number;
  pending_analysis: number;
  processable_pdfs: number;
  generated_at: string;
};

export type ReferralInboxProcessedDocument = {
  document_id: string;
  case_id: string | null;
  document_title: string;
  source_uri: string;
  decision: string;
  status: string;
};

export type ReferralInboxProcessResult = {
  requested_limit: number;
  processed: number;
  skipped: number;
  documents: ReferralInboxProcessedDocument[];
  inbox: ReferralInboxSummary;
  summary: ReferralBatchSummary;
};

export type ReferralInboxUploadResult = {
  uploaded: number;
  rejected: Array<{ file_name: string; reason: string }>;
  files: string[];
  inbox: ReferralInboxSummary;
};

export type ReferralDemoResetResult = {
  documents_deleted: number;
  pages_deleted: number;
  cases_deleted: number;
  reviews_deleted: number;
  events_deleted: number;
  inbox_files_deleted: number;
  output_files_deleted: number;
  inbox: ReferralInboxSummary;
  summary: ReferralBatchSummary;
};

export type RuntimeModelConfig = {
  base_url: string | null;
  model_id: string | null;
  api_key_configured: boolean;
  timeout_seconds: number | null;
  configured: boolean;
};

export type RuntimeModelConfigWrite = {
  base_url: string;
  model_id: string;
  api_key?: string | null;
  timeout_seconds?: number | null;
};

export type RuntimeModelSmokeResult = {
  status: "connected" | "failed";
  message?: string;
  model_id?: string;
  base_url?: string;
  result?: Record<string, unknown>;
};

export type GuidelineAnswer = {
  question_id: string | null;
  answer: string;
  confidence: string;
  limitations: string | null;
  escalation_required: boolean;
  escalation_contact: string | null;
  safety_flags: string[];
  sources: Array<{
    document_id: string;
    title: string;
    version: string;
    chunk_id: string;
    page: number | null;
    quote: string;
  }>;
};

export type Health = {
  status: string;
  db: string;
  queue: string;
  model_gateway: string;
  generation_model_id: string;
  embedding_model_id: string;
  no_external_ai_calls: boolean;
  writeback_enabled: boolean;
  runtime_model_configured?: boolean;
  local_llm_url_allowed?: boolean | null;
  local_llm_base_url_host?: string | null;
};

export type AuditEvent = {
  id: string;
  actor_id: string;
  action: string;
  object_type: string;
  object_id: string;
  payload_json: Record<string, unknown> | null;
  created_at: string;
};

async function request<T>(
  path: string,
  options: RequestInit = {},
  user: UserKey,
  timeoutMs = REQUEST_TIMEOUT_MS
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    const isFormData = options.body instanceof FormData;
    const headers: Record<string, string> = {
      "X-Demo-User": user
    };
    if (!isFormData) {
      headers["Content-Type"] = "application/json";
    }
    Object.assign(headers, options.headers ?? {});
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      signal: controller.signal,
      headers
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("Backend antwortet nicht. Bitte Backend pruefen und erneut versuchen.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      detail = parsed.detail ?? text;
    } catch {
      detail = text;
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

async function requestBlob(
  path: string,
  options: RequestInit = {},
  user: UserKey,
  timeoutMs = REQUEST_TIMEOUT_MS
): Promise<Blob> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      signal: controller.signal,
      headers: {
        "X-Demo-User": user,
        ...(options.headers ?? {})
      }
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("Backend antwortet nicht. Bitte Backend pruefen und erneut versuchen.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      detail = parsed.detail ?? text;
    } catch {
      detail = text;
    }
    throw new Error(detail);
  }
  return response.blob();
}

export const api = {
  health: (user: UserKey) => request<Health>("/api/health", {}, user),
  documents: (user: UserKey) => request<DocumentRead[]>("/api/documents", {}, user),
  documentPages: (id: string, user: UserKey) =>
    request<DocumentPage[]>(`/api/documents/${id}/pages`, {}, user),
  documentFile: (id: string, user: UserKey) =>
    requestBlob(`/api/documents/${id}/file`, {}, user, LONG_REQUEST_TIMEOUT_MS),
  referralCases: (user: UserKey, filter: ReferralWorklistFilter = "all") =>
    request<ReferralWorklistItem[]>(`/api/referrals/cases?filter=${filter}`, {}, user),
  referralBatchSummary: (user: UserKey) =>
    request<ReferralBatchSummary>("/api/referrals/batch-summary", {}, user),
  analyzeReferral: (documentId: string, user: UserKey) =>
    request<ReferralCase>(`/api/referrals/analyze/${documentId}`, { method: "POST" }, user, LONG_REQUEST_TIMEOUT_MS),
  getReferralCase: (caseId: string, user: UserKey) =>
    request<ReferralCase>(`/api/referrals/${caseId}`, {}, user),
  reviewReferral: (
    caseId: string,
    decision: "confirm" | "correct" | "reject" | "question",
    correctedAnalysis: ReferralAnalysis | null,
    user: UserKey,
    comment: string | null = null
  ) =>
    request(`/api/referrals/${caseId}/review`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        corrected_analysis: correctedAnalysis,
        comment
      })
    }, user),
  writebackReferral: (caseId: string, user: UserKey) =>
    request<ReferralWritebackResult>(`/api/referrals/${caseId}/writeback`, { method: "POST" }, user),
  pipelineEvents: (
    user: UserKey,
    options: { limit?: number; documentId?: string; caseId?: string } = {}
  ) => {
    const params = new URLSearchParams();
    params.set("limit", String(options.limit ?? 80));
    if (options.documentId) params.set("document_id", options.documentId);
    if (options.caseId) params.set("case_id", options.caseId);
    return request<ReferralPipelineEvent[]>(`/api/referrals/pipeline-events?${params.toString()}`, {}, user);
  },
  demoOutputs: (user: UserKey, limit = 20) =>
    request<ReferralDemoOutput[]>(`/api/referrals/demo-outputs?limit=${limit}`, {}, user),
  routingTargets: (user: UserKey) => request<ReferralRoutingTarget[]>("/api/referrals/routing-targets", {}, user),
  ingestReferralDemoSources: (user: UserKey) =>
    request<ReferralIngestReport>(
      "/api/referrals/ingest-demo-sources",
      { method: "POST" },
      user,
      LONG_REQUEST_TIMEOUT_MS
    ),
  referralInboxSummary: (user: UserKey) =>
    request<ReferralInboxSummary>("/api/referrals/inbox-summary", {}, user),
  uploadReferralInbox: (user: UserKey, files: File[]) => {
    const form = new FormData();
    for (const file of files) {
      form.append("files", file, file.name);
    }
    return request<ReferralInboxUploadResult>(
      "/api/referrals/inbox/upload",
      {
        method: "POST",
        body: form
      },
      user,
      LONG_REQUEST_TIMEOUT_MS
    );
  },
  processReferralInbox: (user: UserKey, limit = 2) =>
    request<ReferralInboxProcessResult>(
      "/api/referrals/process-inbox",
      {
        method: "POST",
        body: JSON.stringify({ limit })
      },
      user,
      LONG_REQUEST_TIMEOUT_MS
    ),
  resetReferralDemo: (user: UserKey) =>
    request<ReferralDemoResetResult>("/api/referrals/demo-reset", { method: "POST" }, user, LONG_REQUEST_TIMEOUT_MS),
  modelConfig: (user: UserKey) => request<RuntimeModelConfig>("/api/runtime/model-config", {}, user),
  saveModelConfig: (user: UserKey, config: RuntimeModelConfigWrite) =>
    request<RuntimeModelConfig>(
      "/api/runtime/model-config",
      {
        method: "POST",
        body: JSON.stringify(config)
      },
      user
    ),
  smokeTestModel: (user: UserKey) =>
    request<RuntimeModelSmokeResult>("/api/runtime/model-smoke-test", { method: "POST" }, user, LONG_REQUEST_TIMEOUT_MS),
  ingestGuidelines: (user: UserKey) =>
    request("/api/guidelines/ingest", { method: "POST" }, user, LONG_REQUEST_TIMEOUT_MS),
  chatGuidelines: (question: string, user: UserKey) =>
    request<GuidelineAnswer>("/api/guidelines/chat", {
      method: "POST",
      body: JSON.stringify({ question })
    }, user, LONG_REQUEST_TIMEOUT_MS),
  feedback: (objectId: string, label: string, user: UserKey) =>
    request("/api/guidelines/feedback", {
      method: "POST",
      body: JSON.stringify({ object_id: objectId, label })
    }, user),
  audit: (user: UserKey) => request<AuditEvent[]>("/api/admin/audit", {}, user)
};
