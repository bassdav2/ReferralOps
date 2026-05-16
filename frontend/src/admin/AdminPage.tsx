import { RefreshCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type AuditEvent, type UserKey } from "../api/client";

type Props = {
  user: UserKey;
};

export function AdminPage({ user }: Props) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [message, setMessage] = useState("");

  async function load() {
    try {
      setEvents(await api.audit(user));
      setMessage("");
    } catch {
      setEvents([]);
      setMessage("Audit ist nur fuer Admin-User sichtbar.");
    }
  }

  useEffect(() => {
    load();
  }, [user]);

  return (
    <section className="module">
      <div className="module-header">
        <div>
          <h1>Audit</h1>
          <p>Modellvorschlaege, Reviews, Chatantworten und Feedback.</p>
        </div>
        <button className="icon-button" title="Audit aktualisieren" onClick={load}>
          <RefreshCcw size={18} />
        </button>
      </div>
      <div className="table-wrap">
        {message && <div className="message-line">{message}</div>}
        <table>
          <thead>
            <tr>
              <th>Zeit</th>
              <th>Akteur</th>
              <th>Aktion</th>
              <th>Objekt</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.id}>
                <td>{new Date(event.created_at).toLocaleString()}</td>
                <td>{event.actor_id}</td>
                <td>{event.action}</td>
                <td>{event.object_type}:{event.object_id.slice(0, 8)}</td>
                <td>
                  <details>
                    <summary>Payload</summary>
                    <pre>{JSON.stringify(event.payload_json ?? {}, null, 2)}</pre>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
