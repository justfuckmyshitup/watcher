const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("localScribe", {
  apiBase: process.env.LOCAL_SCRIBE_API_BASE || "http://127.0.0.1:8765/api",
  platform: process.platform,
  getCaptureSources: () => ipcRenderer.invoke("local-scribe:capture-sources"),
  setCaptureSource: (sourceId) => ipcRenderer.invoke("local-scribe:set-capture-source", sourceId)
});
