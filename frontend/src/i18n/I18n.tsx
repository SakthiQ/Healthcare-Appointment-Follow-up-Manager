import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import en, { type MessageKey } from '../locales/en';
import hi from '../locales/hi';
import ta from '../locales/ta';
import { setDisplayLocale } from '../lib/format';

/**
 * A small typed translation layer: one dictionary per language in src/locales, a provider that
 * remembers the choice, and useT() for components. Chosen over i18next because the app needs
 * only plain strings with {placeholders}; this adds no dependency, and TypeScript rejects a key
 * that does not exist in the English dictionary.
 */

export type Lang = 'en' | 'ta' | 'hi';

export const LANGUAGES: { code: Lang; label: string }[] = [
  { code: 'en', label: 'English' },
  { code: 'ta', label: 'தமிழ்' },
  { code: 'hi', label: 'हिन्दी' },
];

export const DICTIONARIES: Record<Lang, Partial<Record<MessageKey, string>>> = { en, ta, hi };
const INTL_LOCALE: Record<Lang, string> = { en: 'en-GB', ta: 'ta-IN', hi: 'hi-IN' };
const STORAGE_KEY = 'healthflow.language';

export type Translate = (key: MessageKey, vars?: Record<string, string | number>) => string;

/** Look a key up in `lang`, falling back to English, never to the raw key. */
export function translate(lang: Lang, key: MessageKey, vars?: Record<string, string | number>): string {
  let text = DICTIONARIES[lang][key] ?? en[key];
  if (vars) for (const [name, value] of Object.entries(vars)) text = text.split(`{${name}}`).join(String(value));
  return text;
}

function storedLanguage(): Lang {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === 'en' || value === 'ta' || value === 'hi') return value;
  } catch {
    // Private mode or blocked storage: fall back to English.
  }
  return 'en';
}

interface I18nState {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: Translate;
}

// Without a provider (for example in a component test) everything is English.
const I18nContext = createContext<I18nState>({
  lang: 'en',
  setLang: () => {},
  t: (key, vars) => translate('en', key, vars),
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(storedLanguage);
  setDisplayLocale(INTL_LOCALE[lang]); // before children render, so their dates use it

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Not remembered, but still switched for this visit.
    }
    setLangState(next);
  }, []);

  const value = useMemo<I18nState>(
    () => ({ lang, setLang, t: (key, vars) => translate(lang, key, vars) }),
    [lang, setLang],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nState {
  return useContext(I18nContext);
}

/** The translate function for the current language. */
export function useT(): Translate {
  return useContext(I18nContext).t;
}

/** A language picker for the header and the sign-in pages. */
export function LanguagePicker() {
  const { lang, setLang, t } = useI18n();
  return (
    <label className="language-picker">
      <span className="sr-only">{t('language.label')}</span>
      <select aria-label={t('language.label')} value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
        {LANGUAGES.map((l) => (
          <option key={l.code} value={l.code} lang={l.code}>
            {l.label}
          </option>
        ))}
      </select>
    </label>
  );
}
