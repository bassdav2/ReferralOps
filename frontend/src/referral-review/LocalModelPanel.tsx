import { Button, InlineLoading, Tag, TextInput } from "@carbon/react";
import { CheckmarkFilled, DataCheck, WarningAltFilled } from "@carbon/icons-react";
import { useEffect, useState } from "react";
import { api, type UserKey } from "../api/client";
import { text, type UiLanguage } from "../i18n";

type Props = {
  user: UserKey;
  language: UiLanguage;
  onHealthRefresh?: () => void;
};

export function LocalModelPanel({ user, language, onHealthRefresh }: Props) {
  const [baseUrl, setBaseUrl] = useState("http://localhost:1234/v1");
  const [modelId, setModelId] = useState("google/gemma-4-31B-it");
  const [timeoutSeconds, setTimeoutSeconds] = useState("0");
  const [busy, setBusy] = useState<"load" | "save" | "test" | null>(null);
  const [status, setStatus] = useState<"idle" | "connected" | "failed" | "saved">("idle");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    setBusy("load");
    api.modelConfig(user)
      .then((config) => {
        if (cancelled) return;
        setBaseUrl(config.base_url ?? "http://localhost:1234/v1");
        setModelId(config.model_id ?? "google/gemma-4-31B-it");
        setTimeoutSeconds(config.timeout_seconds === null ? "0" : String(config.timeout_seconds));
        setStatus(config.configured ? "saved" : "idle");
        setMessage(
          config.api_key_configured
            ? text(language, "API-Key wird aus LOCAL_LLM_API_KEY gelesen.", "API key is read from LOCAL_LLM_API_KEY.")
            : ""
        );
      })
      .catch((error) => {
        if (!cancelled) {
          setStatus("failed");
          setMessage(error instanceof Error ? error.message : text(language, "Modell-Konfiguration konnte nicht geladen werden", "Could not load model configuration"));
        }
      })
      .finally(() => {
        if (!cancelled) setBusy(null);
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  async function saveConfig() {
    if (!baseUrl.trim() || !modelId.trim()) {
      setStatus("failed");
      setMessage(text(language, "Base URL und Model ID sind erforderlich.", "Base URL and model ID are required."));
      return false;
    }
    setBusy("save");
    try {
      const timeout = Number(timeoutSeconds);
      if (!Number.isFinite(timeout) || timeout < 0) {
        setStatus("failed");
        setMessage(text(language, "Timeout muss 0 oder groesser sein.", "Timeout must be 0 or greater."));
        return false;
      }
      await api.saveModelConfig(user, {
        base_url: baseUrl.trim(),
        model_id: modelId.trim(),
        timeout_seconds: timeout
      });
      setStatus("saved");
      setMessage(text(language, "Lokales Modell gespeichert.", "Local model saved."));
      onHealthRefresh?.();
      return true;
    } catch (error) {
      setStatus("failed");
      setMessage(error instanceof Error ? error.message : text(language, "Modell-Konfiguration konnte nicht gespeichert werden", "Could not save model configuration"));
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function smokeTest() {
    const saved = await saveConfig();
    if (!saved) return;
    setBusy("test");
    try {
      const result = await api.smokeTestModel(user);
      if (result.status === "connected") {
        setStatus("connected");
        setMessage(`Verbunden: ${result.model_id ?? modelId}`);
      } else {
        setStatus("failed");
        setMessage(result.message ?? text(language, "Smoke-Test fehlgeschlagen", "Smoke test failed"));
      }
      onHealthRefresh?.();
    } catch (error) {
      setStatus("failed");
      setMessage(error instanceof Error ? error.message : text(language, "Smoke-Test fehlgeschlagen", "Smoke test failed"));
    } finally {
      setBusy(null);
    }
  }

  const tagType = status === "connected" ? "green" : status === "failed" ? "red" : "gray";
  const TagIcon = status === "connected" ? CheckmarkFilled : status === "failed" ? WarningAltFilled : DataCheck;

  return (
    <section className="local-model-panel">
      <div className="local-model-head">
        <div>
          <span className="eyebrow">Local Model</span>
          <h2>{text(language, "OpenAI-kompatibler Endpunkt", "OpenAI-compatible endpoint")}</h2>
        </div>
        <Tag renderIcon={TagIcon} size="sm" type={tagType}>
          {status === "connected" ? "connected" : status === "failed" ? "failed" : "local config"}
        </Tag>
      </div>
      <div className="local-model-fields">
        <TextInput
          id="local-model-base-url"
          labelText="Base URL"
          size="sm"
          value={baseUrl}
          onChange={(event) => setBaseUrl(event.target.value)}
        />
        <TextInput
          id="local-model-id"
          labelText="Model ID"
          size="sm"
          value={modelId}
          onChange={(event) => setModelId(event.target.value)}
        />
        <TextInput
          id="local-model-timeout"
          labelText="Timeout s"
          size="sm"
          min={0}
          type="number"
          value={timeoutSeconds}
          onChange={(event) => setTimeoutSeconds(event.target.value)}
        />
        <Button disabled={busy !== null} kind="secondary" onClick={saveConfig} size="sm" type="button">
          {text(language, "Speichern", "Save")}
        </Button>
        <Button disabled={busy !== null} kind="primary" onClick={smokeTest} size="sm" type="button">
          {text(language, "Verbindung testen", "Test connection")}
        </Button>
      </div>
      {busy && (
        <InlineLoading
          status="active"
          description={busy === "test" ? text(language, "Smoke-Test laeuft", "Smoke test running") : text(language, "Speichert", "Saving")}
        />
      )}
      {message && <div className="message-line">{message}</div>}
    </section>
  );
}
