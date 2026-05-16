import { BookOpen, CheckCircle2, Database, Send, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { api, type GuidelineAnswer, type UserKey } from "../api/client";

type Props = {
  user: UserKey;
};

const demoQuestions = [
  "Wie beantrage ich einen KIS-Zugang?",
  "Was mache ich administrativ nach einer Nadelstichverletzung?",
  "Welche Pflichtschulungen brauche ich beim Eintritt?",
  "Darf die KI automatisch ins DMS schreiben?",
  "Soll Patient Max Muster heute entlassen werden?"
];

export function GuidelineChatPage({ user }: Props) {
  const [question, setQuestion] = useState(demoQuestions[0]);
  const [answer, setAnswer] = useState<GuidelineAnswer | null>(null);
  const [message, setMessage] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);

  const isBusy = busyAction !== null;

  async function ingest() {
    setBusyAction("ingest");
    try {
      const result = await api.ingestGuidelines(user);
      setMessage(JSON.stringify(result));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ingestion fehlgeschlagen");
    } finally {
      setBusyAction(null);
    }
  }

  async function ask(nextQuestion = question) {
    setQuestion(nextQuestion);
    setBusyAction("ask");
    try {
      setMessage("Suche lokale Quellen");
      const result = await api.chatGuidelines(nextQuestion, user);
      setAnswer(result);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Frage fehlgeschlagen");
    } finally {
      setBusyAction(null);
    }
  }

  async function feedback(label: string) {
    if (!answer?.question_id) {
      setMessage("Feedback benoetigt eine gespeicherte Antwort.");
      return;
    }
    setBusyAction(`feedback-${label}`);
    try {
      await api.feedback(answer.question_id, label, user);
      setMessage(`Feedback gespeichert: ${label}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Feedback fehlgeschlagen");
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <section className="module">
      <div className="module-header">
        <div>
          <h1>Richtlinien-Chat</h1>
          <p>Antwort basiert nur auf freigegebenen internen Quellen.</p>
        </div>
        <button className="icon-button" title="Demo-Richtlinien indexieren" onClick={ingest} disabled={isBusy}>
          <Database size={18} />
        </button>
      </div>

      <div className="chat-grid">
        <div className="chat-pane">
          <div className="quick-prompts">
            {demoQuestions.map((item) => (
              <button key={item} onClick={() => ask(item)} disabled={isBusy}>
                {item}
              </button>
            ))}
          </div>
          <div className="composer">
            <textarea value={question} onChange={(event) => setQuestion(event.target.value)} disabled={isBusy} />
            <button title="Frage senden" onClick={() => ask()} disabled={isBusy}>
              <Send size={17} />
              Fragen
            </button>
          </div>
          <div className={`answer-box ${answer?.confidence === "no_answer" ? "no-answer" : ""}`}>
            {answer ? (
              <>
                <div className="answer-head">
                  <BookOpen size={19} />
                  <strong>{answer.confidence}</strong>
                </div>
                <p>{answer.answer}</p>
                {answer.limitations && <small>{answer.limitations}</small>}
                <div className="button-row">
                  <button title="Korrekt" onClick={() => feedback("correct")} disabled={isBusy}>
                    <ThumbsUp size={17} />
                    korrekt
                  </button>
                  <button title="Unklar" onClick={() => feedback("unclear")} disabled={isBusy}>
                    <ThumbsDown size={17} />
                    unklar
                  </button>
                </div>
              </>
            ) : (
              <span>Keine Antwort geladen</span>
            )}
          </div>
          {message && <div className="message-line">{message}</div>}
        </div>

        <aside className="sources-pane">
          <h2>Quellen</h2>
          {answer?.sources.length ? (
            answer.sources.map((source) => (
              <article className="source-card" key={source.chunk_id}>
                <div>
                  <CheckCircle2 size={17} />
                  <strong>{source.title}</strong>
                </div>
                <span>Version {source.version}</span>
                <p>{source.quote}</p>
              </article>
            ))
          ) : (
            <div className="empty-state">Keine Quelle fuer diese Antwort.</div>
          )}
        </aside>
      </div>
    </section>
  );
}
