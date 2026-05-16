import { Button, Select, SelectItem, Tag } from "@carbon/react";
import {
  Activity,
  Chat,
  CheckmarkFilled,
  DocumentView,
  Hospital,
  ServerDns,
  WarningAltFilled
} from "@carbon/icons-react";
import type { ReactNode } from "react";
import type { Health, UserKey } from "../api/client";
import { text, type UiLanguage } from "../i18n";

type Section = "referrals" | "guidelines" | "admin";

type Props = {
  active: Section;
  setActive: (section: Section) => void;
  user: UserKey;
  setUser: (user: UserKey) => void;
  health: Health | null;
  language: UiLanguage;
  setLanguage: (language: UiLanguage) => void;
  children: ReactNode;
};

const users: UserKey[] = [
  "sekretariat_kardiologie",
  "hygiene_user",
  "it_admin",
  "restricted_user"
];

const USER_LABELS: Record<UserKey, string> = {
  sekretariat_kardiologie: "Zentrale Zuweisungsstelle",
  hygiene_user: "Hygiene-Team",
  it_admin: "IT/Admin Demo",
  restricted_user: "Eingeschraenkt"
};

export function Layout({ active, setActive, user, setUser, health, language, setLanguage, children }: Props) {
  const gatewayLabel = health?.model_gateway ?? "loading";
  const gatewayWarn = !health || health.status !== "ok";
  const egressLabel = health?.no_external_ai_calls ? "local only" : "egress enabled";
  const egressWarn = health ? !health.no_external_ai_calls : true;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <Hospital size={18} />
          </div>
          <div>
            <strong>Hospital AI</strong>
            <span>Operations console</span>
          </div>
        </div>
        <nav className="nav" aria-label="Primary">
          <Button
            className={active === "referrals" ? "active" : ""}
            kind="ghost"
            onClick={() => setActive("referrals")}
            renderIcon={DocumentView}
            size="lg"
            type="button"
          >
            <span>{text(language, "Zuweisungen", "Referrals")}</span>
          </Button>
          <Button
            className={active === "guidelines" ? "active" : ""}
            kind="ghost"
            onClick={() => setActive("guidelines")}
            renderIcon={Chat}
            size="lg"
            type="button"
          >
            <span>{text(language, "Richtlinien", "Guidelines")}</span>
          </Button>
          {user === "it_admin" && (
            <Button
              className={active === "admin" ? "active" : ""}
              kind="ghost"
              onClick={() => setActive("admin")}
              renderIcon={Activity}
              size="lg"
              type="button"
            >
              <span>Audit</span>
            </Button>
          )}
        </nav>
      </aside>
      <header className="topbar">
        <div className="status-cluster">
          <Tag className="shell-tag" renderIcon={gatewayWarn ? WarningAltFilled : CheckmarkFilled} size="sm" type={gatewayWarn ? "warm-gray" : "green"}>
            {gatewayLabel}
          </Tag>
          <Tag className="shell-tag" renderIcon={egressWarn ? WarningAltFilled : ServerDns} size="sm" type={egressWarn ? "warm-gray" : "green"}>
            {egressLabel}
          </Tag>
        </div>
        <div className="user-picker">
          <Select
            id="ui-language"
            inline
            labelText={text(language, "Sprache", "Language")}
            size="sm"
            value={language}
            onChange={(event) => setLanguage(event.target.value as UiLanguage)}
          >
            <SelectItem value="de" text="DE" />
            <SelectItem value="en" text="EN" />
          </Select>
          <Select
            id="demo-user"
            inline
            labelText="Demo user"
            size="sm"
            value={user}
            onChange={(event) => setUser(event.target.value as UserKey)}
          >
            {users.map((item) => (
              <SelectItem value={item} key={item} text={USER_LABELS[item]} />
            ))}
          </Select>
        </div>
      </header>
      <main className="workspace">{children}</main>
    </div>
  );
}
