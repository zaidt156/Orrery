const { app, BrowserWindow, clipboard, dialog, ipcMain, shell } = require("electron");
const { autoUpdater } = require("electron-updater");
const { spawn } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const SOURCE_ROOT = path.resolve(__dirname, "..", "..");
const API_HOST = process.env.ORRERY_API_HOST || "127.0.0.1";
const API_PORT = Number(process.env.ORRERY_API_PORT || "8765");
const SESSION_TOKEN = process.env.ORRERY_SESSION_TOKEN || crypto.randomBytes(32).toString("base64url");
const START_URL = `http://${API_HOST}:${API_PORT}/?token=${encodeURIComponent(SESSION_TOKEN)}`;

let mainWindow = null;
let backendProcess = null;

function logDir() {
  const dir = app.isPackaged ? path.join(app.getPath("userData"), "logs") : path.join(SOURCE_ROOT, "logs");
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function resolvePython() {
  if (process.env.ORRERY_PYTHON) return process.env.ORRERY_PYTHON;
  const windowsVenv = path.join(SOURCE_ROOT, ".venv", "Scripts", "python.exe");
  const posixVenv = path.join(SOURCE_ROOT, ".venv", "bin", "python");
  if (fs.existsSync(windowsVenv)) return windowsVenv;
  if (fs.existsSync(posixVenv)) return posixVenv;
  return process.platform === "win32" ? "python" : "python3";
}

function resolveBackendCommand() {
  if (process.env.ORRERY_BACKEND_EXE) {
    return { command: process.env.ORRERY_BACKEND_EXE, args: ["--backend-only"], cwd: SOURCE_ROOT };
  }

  if (app.isPackaged) {
    const exe = process.platform === "win32" ? "OrreryBackend.exe" : "OrreryBackend";
    const packagedBackend = path.join(process.resourcesPath, "backend", exe);
    if (fs.existsSync(packagedBackend)) {
      return { command: packagedBackend, args: ["--backend-only"], cwd: path.dirname(packagedBackend) };
    }
  }

  return { command: resolvePython(), args: ["app.py", "--backend-only"], cwd: SOURCE_ROOT };
}

function startBackend() {
  if (backendProcess) return;
  const backend = resolveBackendCommand();
  const logPath = path.join(logDir(), "electron-backend.log");
  const logStream = fs.createWriteStream(logPath, { flags: "a" });
  const env = {
    ...process.env,
    ORRERY_SESSION_TOKEN: SESSION_TOKEN,
    ORRERY_API_HOST: API_HOST,
    ORRERY_API_PORT: String(API_PORT),
    // The PyInstaller backend lives inside resources/. Never let mutable memory, generated files,
    // config, or caches land in that signed/update-replaced application directory.
    ORRERY_DATA_DIR: app.getPath("userData"),
  };

  backendProcess = spawn(backend.command, backend.args, {
    cwd: backend.cwd,
    env,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });

  backendProcess.stdout.pipe(logStream);
  backendProcess.stderr.pipe(logStream);
  backendProcess.on("error", (error) => {
    backendProcess = null;
    logStream.write(`\n[orrery-electron] backend failed to launch: ${error.message}\n`);
    logStream.end();
  });
  backendProcess.on("exit", (code, signal) => {
    backendProcess = null;
    logStream.write(`\n[orrery-electron] backend exited code=${code} signal=${signal}\n`);
    logStream.end();
  });
}

async function waitForBackend(timeoutMs = 600000) {
  // Generous by design: a truly fresh install may be pulling the bundled database image.
  // Real failures exit the backend process, which stops the health probe well before this.
  const deadline = Date.now() + timeoutMs;
  const url = `http://${API_HOST}:${API_PORT}/api/health`;
  while (Date.now() < deadline) {
    if (!backendProcess) {
      // give the log pipes a beat to flush so the setup markers are readable
      await new Promise((resolve) => setTimeout(resolve, 300));
      throw new Error("The Orrery backend exited during startup (see logs).");
    }
    try {
      const response = await fetch(url, { headers: { "X-Orrery-Token": SESSION_TOKEN } });
      if (response.ok) return;
    } catch {
      // backend is still starting
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Orrery backend did not become ready at ${url}`);
}

function stopBackend() {
  if (!backendProcess || backendProcess.killed) return;
  const pid = backendProcess.pid;
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(pid), "/T", "/F"], { windowsHide: true });
  } else {
    backendProcess.kill("SIGTERM");
  }
}

const DOCKER_URL = "https://www.docker.com/products/docker-desktop/";

function backendLogTail() {
  try {
    const p = path.join(logDir(), "electron-backend.log");
    const size = fs.statSync(p).size;
    const len = Math.min(size, 8192);
    const buf = Buffer.alloc(len);
    const fd = fs.openSync(p, "r");
    fs.readSync(fd, buf, 0, len, size - len);
    fs.closeSync(fd);
    return buf.toString("utf8");
  } catch {
    return "";
  }
}

function openDockerDesktop() {
  if (process.platform === "win32") {
    const exe = path.join(process.env.ProgramFiles || "C:\\Program Files", "Docker", "Docker", "Docker Desktop.exe");
    if (fs.existsSync(exe)) {
      spawn(exe, [], { detached: true, stdio: "ignore" }).unref();
      return;
    }
  } else if (process.platform === "darwin") {
    spawn("open", ["-a", "Docker"], { stdio: "ignore" }).unref();
    return;
  }
  shell.openExternal(DOCKER_URL);
}

// First-run setup help: the backend prints ORRERY_SETUP:* markers to its log when it can't
// start a database on its own; turn those into a dialog with the actual next step.
async function showSetupDialog() {
  const tail = backendLogTail();
  if (tail.includes("ORRERY_SETUP:DOCKER_MISSING")) {
    const r = await dialog.showMessageBox({
      type: "info",
      title: "Orrery needs a database",
      message: "Install Docker Desktop and Orrery sets up its database automatically",
      detail: "Orrery could not find Docker Desktop. Install it, then reopen Orrery - the bundled PostgreSQL database is created for you. Already run your own PostgreSQL? Start Orrery once from a terminal to enter its connection string.",
      buttons: ["Get Docker Desktop", "Close"],
      defaultId: 0,
      cancelId: 1,
    });
    if (r.response === 0) shell.openExternal(DOCKER_URL);
    return true;
  }
  if (tail.includes("ORRERY_SETUP:DOCKER_STOPPED") || tail.includes("ORRERY_SETUP:PROVISION_FAILED")) {
    const r = await dialog.showMessageBox({
      type: "info",
      title: "Start Docker Desktop",
      message: "Docker Desktop is installed but not running",
      detail: "Start Docker Desktop, then reopen Orrery - the bundled database starts automatically.",
      buttons: ["Open Docker Desktop", "Close"],
      defaultId: 0,
      cancelId: 1,
    });
    if (r.response === 0) openDockerDesktop();
    return true;
  }
  return false;
}

function createWindow() {
  const iconDir = app.isPackaged ? path.join(process.resourcesPath, "assets", "desktop") : path.join(SOURCE_ROOT, "assets", "desktop");
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 940,
    minHeight: 640,
    title: "Orrery",
    icon: path.join(iconDir, process.platform === "win32" ? "orrery.ico" : "orrery.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http://") || url.startsWith("https://")) {
      shell.openExternal(url);
      return { action: "deny" };
    }
    return { action: "deny" };
  });

  mainWindow.loadURL(START_URL);
}

async function startAndCreateWindow() {
  startBackend();
  await waitForBackend();
  createWindow();
}

ipcMain.handle("orrery:save-file", async (_event, payload = {}) => {
  const filename = String(payload.filename || "orrery-file");
  const b64 = String(payload.b64 || "");
  const result = await dialog.showSaveDialog(mainWindow, {
    defaultPath: filename,
    properties: ["showOverwriteConfirmation"],
  });
  if (result.canceled || !result.filePath) return { ok: false, cancelled: true };
  await fs.promises.writeFile(result.filePath, Buffer.from(b64, "base64"));
  return { ok: true, path: result.filePath };
});

ipcMain.handle("orrery:copy-text", async (_event, text = "") => {
  clipboard.writeText(String(text ?? ""));
  return { ok: true };
});

ipcMain.handle("orrery:desktop-info", () => ({
  shell: "electron",
  appVersion: app.getVersion(),
  platform: process.platform,
  apiBase: `http://${API_HOST}:${API_PORT}`,
}));

ipcMain.handle("orrery:check-native-updates", async () => {
  if (!app.isPackaged) {
    return { supported: false, message: "Native auto-update is available only in packaged Electron builds." };
  }
  try {
    const result = await autoUpdater.checkForUpdates();
    return { supported: true, updateInfo: result?.updateInfo || null };
  } catch (error) {
    return { supported: true, error: error.message || String(error) };
  }
});

async function reportStartupFailure(error) {
  const handled = await showSetupDialog();
  if (!handled) dialog.showErrorBox("Orrery startup failed", error.message || String(error));
}

app.whenReady().then(async () => {
  try {
    await startAndCreateWindow();
  } catch (error) {
    await reportStartupFailure(error);
    app.quit();
  }
});

app.on("activate", async () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    try {
      await startAndCreateWindow();
    } catch (error) {
      await reportStartupFailure(error);
    }
  }
});

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", stopBackend);
