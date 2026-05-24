const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("watcher", {
  apiBase: process.env.WATCHER_API_BASE || "http://127.0.0.1:8765/api",
  platform: process.platform,
  getCaptureSources: () => ipcRenderer.invoke("watcher:capture-sources"),
  setCaptureSource: (sourceId) => ipcRenderer.invoke("watcher:set-capture-source", sourceId)
});
