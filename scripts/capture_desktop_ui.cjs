const { app, BrowserWindow } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const outputPath = path.join(root, "docs", "assets", "watcher-dashboard-render.png");

async function main() {
  await app.whenReady();
  const win = new BrowserWindow({
    width: 1440,
    height: 920,
    show: false,
    backgroundColor: "#f6f8f8",
    webPreferences: {
      preload: path.join(root, "apps", "desktop", "electron", "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  await win.loadFile(path.join(root, "apps", "desktop", "dist", "index.html"));
  await new Promise((resolve) => setTimeout(resolve, 3500));
  const image = await win.webContents.capturePage();
  fs.writeFileSync(outputPath, image.toPNG());
  app.quit();
}

main().catch((error) => {
  console.error(error);
  app.quit();
  process.exitCode = 1;
});

