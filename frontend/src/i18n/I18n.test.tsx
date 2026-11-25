import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import en, { type MessageKey } from '../locales/en';
import hi from '../locales/hi';
import ta from '../locales/ta';
import { formatDate, setDisplayLocale } from '../lib/format';
import { DICTIONARIES, I18nProvider, LanguagePicker, translate, useT } from './I18n';

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe('translations', () => {
  it.each([['ta', ta], ['hi', hi]] as const)('%s has every English key, non-empty, with the same placeholders', (_, dict) => {
    const missing = (Object.keys(en) as MessageKey[]).filter((key) => !dict[key]?.trim());
    expect(missing).toEqual([]);
    for (const key of Object.keys(en) as MessageKey[]) {
      expect(placeholders(dict[key]), key).toEqual(placeholders(en[key]));
    }
  });

  it('falls back to English for a missing key, never to the raw key', () => {
    const saved = DICTIONARIES.ta['login.title'];
    delete DICTIONARIES.ta['login.title'];
    try {
      expect(translate('ta', 'login.title')).toBe('Sign in');
    } finally {
      DICTIONARIES.ta['login.title'] = saved;
    }
  });

  it('fills in placeholders', () => {
    expect(translate('en', 'search.minutes', { count: 30 })).toBe('30 minutes');
    expect(translate('hi', 'search.minutes', { count: 30 })).toBe('30 मिनट');
  });
});

function Title() {
  const t = useT();
  return <h1>{t('login.title')}</h1>;
}

describe('language picker', () => {
  afterEach(() => {
    localStorage.clear();
    setDisplayLocale('en-GB');
  });

  it('switches the language, remembers it and sets <html lang>', async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <LanguagePicker />
        <Title />
      </I18nProvider>,
    );
    expect(screen.getByRole('heading')).toHaveTextContent('Sign in');

    await user.selectOptions(screen.getByLabelText('Language'), 'ta');

    expect(screen.getByRole('heading')).toHaveTextContent('உள்நுழைக');
    expect(localStorage.getItem('healthflow.language')).toBe('ta');
    expect(document.documentElement.lang).toBe('ta');
    expect(screen.getByLabelText('மொழி')).toHaveValue('ta');
  });

  it('starts in the remembered language', () => {
    localStorage.setItem('healthflow.language', 'hi');
    render(
      <I18nProvider>
        <Title />
      </I18nProvider>,
    );
    expect(screen.getByRole('heading')).toHaveTextContent('साइन इन करें');
  });

  it('formats dates in the chosen language', () => {
    setDisplayLocale('en-GB');
    const english = formatDate('2030-01-07T09:00:00Z', 'UTC');
    setDisplayLocale('hi-IN');
    const hindi = formatDate('2030-01-07T09:00:00Z', 'UTC');
    expect(english).toContain('Jan');
    expect(hindi).not.toEqual(english);
    expect(hindi).toMatch(/[ऀ-ॿ]/); // Devanagari
  });
});
