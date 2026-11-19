// The ClaimTrace engine, in a Web Worker: Pyodide (Python compiled to WebAssembly) plus the ClaimTrace
// wheel, all served from this site (./pyodide/, built by scripts/build_try_bundle.py). try.js starts this
// worker from a blob: URL so it runs under the page's Content-Security-Policy (connect-src 'self'): the
// worker cannot reach any other origin either.
//
// Protocol. In:  {id, op, args, files?: [{name, buffer: ArrayBuffer}]}
//           Out: {id, ok: true, result} | {id, ok: false, error: {code, message}}
//                {type: "progress", phase: "download" | "start" | "ready" | "failed", loaded, total}
//
// Python running here cannot be interrupted, so try.js stops a call that runs too long (its watchdog) or that
// the person cancels by terminating this worker, and starts a new one for the next action.

const BASE = new URL('./pyodide/', import.meta.url).href;
const realFetch = globalThis.fetch.bind(globalThis);

let total = 0;
let loaded = 0;
let counting = false;
let lastPost = 0;

function progress(phase, force = false) {
  const now = Date.now();
  if (!force && now - lastPost < 120) return;
  lastPost = now;
  self.postMessage({ type: 'progress', phase, loaded: Math.min(loaded, total || loaded), total });
}

// Count the bytes Pyodide downloads (the wasm binary, the standard library, the wheels) as they arrive.
// Only same-origin requests are possible here; the counter just reports them.
globalThis.fetch = async (input, init) => {
  const res = await realFetch(input, init);
  if (!counting || !res.ok || !res.body) return res;
  const counter = new TransformStream({
    transform(chunk, controller) {
      loaded += chunk.byteLength;
      progress('download');
      controller.enqueue(chunk);
    },
  });
  return new Response(res.body.pipeThrough(counter), { status: res.status, statusText: res.statusText, headers: res.headers });
};

let call = null;

const ready = (async () => {
  const manifest = await (await realFetch(BASE + 'manifest.json')).json();
  const size = (name) => (manifest.files.find((f) => f.file === name) || { size: 0 }).size;
  total = manifest.total_bytes;
  progress('download', true);
  counting = true;
  // pyodide.mjs and pyodide.asm.mjs arrive as module imports, not fetches: counted once they are in.
  const { loadPyodide } = await import(BASE + 'pyodide.mjs');
  loaded += size('pyodide.mjs');
  const py = await loadPyodide({
    indexURL: BASE,
    lockFileURL: BASE + 'pyodide-lock.json',
    stdout: () => {},
    stderr: () => {},
  });
  loaded += size('pyodide.asm.mjs');
  progress('download', true);
  await py.loadPackage(manifest.load, { messageCallback: () => {}, errorCallback: () => {} });
  counting = false;
  loaded = total;
  progress('start', true);
  const facade = py.pyimport('claimtrace.browser');
  call = (request, files) => {
    const pyFiles = files ? py.toPy(files) : undefined;
    try {
      return facade.call(request, pyFiles);
    } finally {
      if (pyFiles) pyFiles.destroy();
    }
  };
  // What actually crossed the network (0 when the browser served its cached copy).
  const transferred = performance.getEntriesByType('resource').reduce((n, e) => n + (e.transferSize || 0), 0);
  self.postMessage({ type: 'progress', phase: 'ready', loaded: total, total, transferred });
})().catch((err) => {
  self.postMessage({ type: 'progress', phase: 'failed', loaded, total, message: String((err && err.message) || err).slice(0, 300) });
  throw err;
});

// One request at a time, in order: the engine is single-threaded and requests build on each other.
let queue = Promise.resolve();

self.onmessage = (event) => {
  const { id, op, args, files } = event.data || {};
  queue = queue.then(async () => {
    try {
      await ready;
    } catch {
      self.postMessage({ id, ok: false, error: { code: 'engine_failed', message: 'The engine could not start in this browser.' } });
      return;
    }
    try {
      const list = files ? files.map((f) => ({ name: f.name, bytes: new Uint8Array(f.buffer) })) : null;
      const reply = JSON.parse(call(JSON.stringify({ op, ...(args || {}) }), list));
      self.postMessage({ id, ...reply });
    } catch (err) {
      self.postMessage({ id, ok: false, error: { code: 'worker_error', message: 'Something went wrong in the engine.' } });
    }
  });
};
