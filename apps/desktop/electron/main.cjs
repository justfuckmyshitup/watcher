const { app, BrowserWindow, Menu, Tray, nativeImage, shell, ipcMain, desktopCapturer, session } = require("electron");
const path = require("node:path");
const { spawn } = require("node:child_process");

const API_PORT = process.env.WATCHER_PORT || "8765";
const API_BASE = `http://127.0.0.1:${API_PORT}/api`;
let mainWindow = null;
let tray = null;
let backendProcess = null;
let selectedCaptureSourceId = null;

function startBackend() {
  if (process.env.WATCHER_SKIP_BACKEND_START === "true") {
    return;
  }
  const repoRoot = path.resolve(__dirname, "../../..");
  const python = process.env.WATCHER_PYTHON || "python";
  backendProcess = spawn(
    python,
    ["-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", API_PORT],
    {
      cwd: repoRoot,
      env: { ...process.env, WATCHER_HOST: "127.0.0.1", WATCHER_PORT: API_PORT },
      stdio: "ignore",
      windowsHide: true
    }
  );
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1080,
    minHeight: 720,
    title: "Watcher",
    backgroundColor: "#f6f8f8",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  }

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http://127.0.0.1") || url.startsWith("http://localhost")) {
      return { action: "allow" };
    }
    shell.openExternal(url);
    return { action: "deny" };
  });
}

function createTray() {
  const icon = nativeImage.createEmpty();
  tray = new Tray(icon);
  tray.setToolTip("Watcher");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Show Watcher", click: () => mainWindow?.show() },
      { label: "Backend: localhost only", enabled: false },
      { type: "separator" },
      { label: "Quit", click: () => app.quit() }
    ])
  );
}

function registerIpcHandlers() {
  session.defaultSession.setDisplayMediaRequestHandler(async (_request, callback) => {
    try {
      const sources = await listCaptureSources();
      const source =
        sources.find((item) => item.id === selectedCaptureSourceId) ??
        sources.find((item) => item.id.startsWith("screen:")) ??
        sources[0];
      callback(source ? { video: source } : {});
    } catch {
      callback({});
    }
  }, { useSystemPicker: false });

  ipcMain.handle("watcher:capture-sources", async () => {
    const sources = await listCaptureSources();
    return sources.map((source) => ({
      id: source.id,
      name: source.name
    }));
  });

  ipcMain.handle("watcher:set-capture-source", async (_event, sourceId) => {
    selectedCaptureSourceId = typeof sourceId === "string" && sourceId.trim() ? sourceId : null;
    return { ok: true };
  });
}

function listCaptureSources() {
  return desktopCapturer.getSources({
    types: ["screen", "window"],
    thumbnailSize: { width: 0, height: 0 },
    fetchWindowIcons: false
  });
}

app.whenReady().then(() => {
  registerIpcHandlers();
  startBackend();
  createWindow();
  createTray();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

app.on("before-quit", () => {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});
