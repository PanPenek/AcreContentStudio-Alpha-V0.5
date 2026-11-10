const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('abs', {
  call: async (channel, arg) => {
    const r = await ipcRenderer.invoke(channel, arg);
    if (!r.ok) throw new Error(r.error);
    return r.data;
  },
  on: (fn) => ipcRenderer.on('evt', (_e, m) => fn(m.channel, m.payload)),
  file: (p) => (p ? `absfile://local/${encodeURIComponent(p.replace(/\\/g, '/'))}?t=${Date.now()}` : ''),
});
