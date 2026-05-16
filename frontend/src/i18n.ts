export type UiLanguage = "de" | "en";

export function text(language: UiLanguage, german: string, english: string) {
  return language === "en" ? english : german;
}
