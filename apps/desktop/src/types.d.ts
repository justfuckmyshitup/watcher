export {};

declare global {
  interface Window {
    localScribe?: {
      apiBase: string;
      platform: string;
      getCaptureSources?: () => Promise<Array<{ id: string; name: string }>>;
      setCaptureSource?: (sourceId: string | null) => Promise<{ ok: boolean }>;
    };
  }
}
