import { useEffect, useState } from "react";
import { api, type Health, type UserKey } from "./api/client";
import { AdminPage } from "./admin/AdminPage";
import { Layout } from "./components/Layout";
import { GuidelineChatPage } from "./guideline-chat/GuidelineChatPage";
import type { UiLanguage } from "./i18n";
import { ReferralReviewPage } from "./referral-review/ReferralReviewPage";

type Section = "referrals" | "guidelines" | "admin";

export default function App() {
  const [active, setActive] = useState<Section>("referrals");
  const [user, setUser] = useState<UserKey>("it_admin");
  const [health, setHealth] = useState<Health | null>(null);
  const [language, setLanguage] = useState<UiLanguage>(() =>
    window.localStorage.getItem("hospital-ai-ui-language") === "en" ? "en" : "de"
  );

  useEffect(() => {
    api.health(user).then(setHealth).catch(() => setHealth(null));
  }, [user]);

  function refreshHealth() {
    api.health(user).then(setHealth).catch(() => setHealth(null));
  }

  useEffect(() => {
    window.localStorage.setItem("hospital-ai-ui-language", language);
  }, [language]);

  useEffect(() => {
    if (user !== "it_admin" && active === "admin") {
      setActive("referrals");
    }
  }, [active, user]);

  return (
    <Layout
      active={active}
      setActive={setActive}
      user={user}
      setUser={setUser}
      health={health}
      language={language}
      setLanguage={setLanguage}
    >
      {active === "referrals" && (
        <ReferralReviewPage user={user} language={language} onHealthRefresh={refreshHealth} />
      )}
      {active === "guidelines" && <GuidelineChatPage user={user} />}
      {active === "admin" && <AdminPage user={user} />}
    </Layout>
  );
}
