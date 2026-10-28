/* PyRogue cold-load helper. Inlined into index.html by make_runtime.py.
 *
 * The big runtime files (main.wasm, main.data) are shipped gzipped (*.gz) and
 * gunzipped here with DecompressionStream, so the bytes on the wire are the
 * same whatever the host does about Content-Encoding. A host that already
 * decodes a .gz (or serves it with Content-Encoding) is handled by checking
 * for the gzip magic. Everything starts downloading from the first line of
 * the page, not from the end of a chain of script loads, and the files the
 * interpreter needs only after it has booted (the pygame wheel, the app) are
 * held back until the big two are in, so they do not slow them down.
 * window.fetch is wrapped so pygbag's own later requests get these responses.
 */
(function () {
  var RT = "rt/";
  var real = window.fetch.bind(window);
  var jobs = new Map();
  var abs = function (u) {
    return new URL(u, document.baseURI).href.split("#")[0].replace(/([^:])\/\/+/g, "$1/");
  };
  var T0 = performance.now();
  window.__rt = { log: [], jobs: jobs };
  function note(m) { window.__rt.log.push([Math.round(performance.now() - T0), m]); }

  function rebuild(reader, first) {
    var pending = first;
    return new ReadableStream({
      pull: function (c) {
        if (pending) {
          var f = pending; pending = null;
          if (f.done) { c.close(); return; }
          c.enqueue(f.value); return;
        }
        return reader.read().then(function (r) { if (r.done) c.close(); else c.enqueue(r.value); });
      },
      cancel: function (why) { return reader.cancel(why); }
    });
  }

  /* fetch url (a .gz or a plain file), gunzip if it is gzip, resolve to a Response */
  function load(url, type, gunzip, onDrained) {
    return real(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error(url + " " + r.status);
      var reader = r.body.getReader();
      return reader.read().then(function (first) {
        var body = rebuild(reader, first);
        var v = first.value;
        if (gunzip && v && v.length > 2 && v[0] === 0x1f && v[1] === 0x8b)
          body = body.pipeThrough(new DecompressionStream("gzip"));
        var two = body.tee();      // one branch drains at network speed, one goes to the consumer
        var drain = two[0].getReader();
        (function pump() {
          drain.read().then(function (x) { if (x.done) { note("drained " + url); if (onDrained) onDrained(); } else pump(); });
        })();
        return new Response(two[1], { status: 200, headers: { "content-type": type } });
      });
    });
  }

  function add(key, file, type, gunzip, onDrained) {
    var k = abs(RT + key);
    note("start " + file);
    var job = load(abs(RT + file), type, gunzip, onDrained);
    job.catch(function (e) { console.error("rt: " + file + " failed", e); });
    jobs.set(k, job);
  }

  window.fetch = function (input, init) {
    var u = abs(typeof input === "string" ? input : (input && input.url) || String(input));
    var j = jobs.get(u);
    if (j) {
      note("serve " + u.slice(-40));
      return j.then(function (r) { return r.clone(); });
    }
    return real(input, init);
  };

  /* a gzipped script, run as an inline script as soon as asked for by jsimport()
     (pythons.js loads the interpreter glue with a <script src>, which cannot gunzip) */
  var scripts = new Map();
  function addScript(key, file) {
    scripts.set(abs(RT + key), load(abs(RT + file), "text/javascript", true).then(function (r) { return r.text(); }));
  }
  window.__rt.script = function (url) {
    var p = scripts.get(abs(url));
    if (!p) return false;
    p.then(function (text) {
      var el = document.createElement("script");
      el.text = text + "\n//# sourceURL=" + abs(url);
      document.head.appendChild(el);
    }, function (e) { console.error("rt: " + url + " failed", e); });
    return true;
  };

  var left = 2;
  function bigDone() { if (--left === 0) lows(); }
  function lows() {
    add("cp312/PYGAME_WHEEL", "cp312/PYGAME_WHEEL", "application/zip", false);
    add("../web.apk", "../web.apk", "application/zip", false);
  }
  add("cpython312/main.wasm", "cpython312/main.wasm.gz", "application/wasm", true, bigDone);
  add("cpython312/main.data", "cpython312/main.data.gz", "application/octet-stream", true, bigDone);
  addScript("cpython312/main.js", "cpython312/main.js.gz");
  add("cpythonrc.py", "cpythonrc.py.gz", "text/plain", true);
  add("index-PYGBAG-cp312.json", "index-PYGBAG-cp312.json", "application/json", false);
})();
