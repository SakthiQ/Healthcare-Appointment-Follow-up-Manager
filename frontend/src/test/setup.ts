import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// React Router 6 prints two upgrade notices per render. They are about its v7 migration,
// not about anything under test, and they bury real warnings.
const originalWarn = console.warn;
console.warn = (...args: unknown[]) => {
  if (typeof args[0] === 'string' && args[0].includes('React Router Future Flag Warning')) return;
  originalWarn(...args);
};

afterEach(() => {
  cleanup();
  localStorage.clear();
});
