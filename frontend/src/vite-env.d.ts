/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_AUTH_COOKIES?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
