const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("pywebview", {
  api: {
    save_file: (filename, b64) => ipcRenderer.invoke("orrery:save-file", { filename, b64 }),
  },
});

contextBridge.exposeInMainWorld("orreryDesktop", {
  info: () => ipcRenderer.invoke("orrery:desktop-info"),
  checkNativeUpdates: () => ipcRenderer.invoke("orrery:check-native-updates"),
});

