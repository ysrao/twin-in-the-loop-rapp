"""Local runner for the rApp console page (artefact v4, Mac).

Serves the repository folder on http://127.0.0.1:8765 and adds one route:

  POST /api/run   body: the run package (JSON, as the console page builds it)
                  -> runs notebook/rapp_run.ipynb with that package (the same
                     code as the notebook: Sionna RT on the local GPU, Sionna
                     SYS), and returns its RESULT as JSON.
  GET  /api/ping  -> {"ok": true}: the page uses it to switch its Run button on.

Local use only: it binds to 127.0.0.1, so nothing outside this Mac can reach it.
Start it with the Desktop launcher, or:
    .venv/bin/python local/rapp_server.py
"""
import copy
import http.server
import json
import os
import socketserver
import sys
import threading
import time
import webbrowser

import nbformat
from nbclient import NotebookClient

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTEBOOK = os.path.join(REPO, "notebook", "rapp_run.ipynb")
PORT = int(os.environ.get("RAPP_PORT", "8765"))
PAGE = "rapp-run-local.html"
_run_lock = threading.Lock()

DUMP_CELL = r'''
import json as _j, math as _m, mitsuba as _mi
def _clean(o):
    # JSON for the browser: numpy -> Python, NaN/inf -> null
    if hasattr(o, "tolist"):
        o = o.tolist()
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        return o if _m.isfinite(o) else None
    if isinstance(o, (str, int, bool)) or o is None:
        return o
    return str(o)
_R = _clean(dict(RESULT))
_R["run"] = {"backend": _mi.variant()}
print("@@RESULT@@" + _j.dumps(_R, allow_nan=False))
'''


def _package_cell_source(pkg):
    """The package cell, holding this package. The JSON is re-serialised with
    every quote escaped, so the text cannot close the r'''...''' string."""
    text = json.dumps(pkg, indent=1, ensure_ascii=True).replace("'", "\\u0027")
    return "PACKAGE_JSON = r'''\n" + text + "\n'''\n"


def run_package(pkg):
    nb = nbformat.read(NOTEBOOK, as_version=4)
    nb = copy.deepcopy(nb)
    mode = str(pkg.get("mode", "single"))
    fn = str(pkg.get("function", "capacity"))
    # settings cell: the package's own mode/function (they also decide the run
    # when the package equals the built-in study package)
    s = nb.cells[2].source
    lines = []
    for ln in s.splitlines(True):
        if ln.startswith("MODE ="):
            ln = f'MODE = {json.dumps(mode)}\n'
        elif ln.startswith("FUNCTION ="):
            ln = f'FUNCTION = {json.dumps(fn)}\n'
        elif ln.startswith("COUNTER_SET ="):
            ln = 'COUNTER_SET = "study"\n'
        elif ln.startswith("PM_CSV ="):
            ln = 'PM_CSV = ""\n'
        lines.append(ln)
    nb.cells[2].source = "".join(lines)
    nb.cells[3].source = _package_cell_source(pkg)
    nb.cells.append(nbformat.v4.new_code_cell(DUMP_CELL))
    for c in nb.cells:
        if c.cell_type == "code":
            c.outputs = []
    t0 = time.time()
    client = NotebookClient(nb, timeout=1800, kernel_name="python3",
                            resources={"metadata": {"path": os.path.dirname(NOTEBOOK)}},
                            allow_errors=True)
    client.execute()
    log, result, error = [], None, None
    for i, c in enumerate(nb.cells):
        if c.cell_type != "code":
            continue
        for o in c.get("outputs", []):
            if o.output_type == "stream":
                txt = o.get("text", "")
                if "@@RESULT@@" in txt:
                    result = json.loads(txt.split("@@RESULT@@", 1)[1])
                else:
                    log.append(txt)
            elif o.output_type == "error" and error is None:
                error = f"{o.ename}: {o.evalue}"
    secs = round(time.time() - t0, 1)
    if error:
        return {"ok": False, "error": error, "log": "".join(log), "seconds": secs}
    if result is None:
        return {"ok": False, "error": "The run finished without a result.", "log": "".join(log), "seconds": secs}
    result["run"]["seconds"] = secs
    return {"ok": True, "result": result, "log": "".join(log), "seconds": secs}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=REPO, **k)

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("%s\n" % (fmt % args))

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/" + PAGE)
            self.end_headers()
            return
        if self.path.startswith("/api/ping"):
            return self._json(200, {"ok": True})
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/run":
            return self._json(404, {"ok": False, "error": "unknown route"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > 5_000_000:
                return self._json(400, {"ok": False, "error": "empty or oversized package"})
            pkg = json.loads(self.rfile.read(n))
            if not isinstance(pkg, dict) or "sites" not in pkg:
                return self._json(400, {"ok": False, "error": "not a run package (no 'sites')"})
        except Exception as e:
            return self._json(400, {"ok": False, "error": f"package is not valid JSON: {e}"})
        if not _run_lock.acquire(blocking=False):
            return self._json(409, {"ok": False, "error": "A run is already in progress - wait for it to finish."})
        try:
            out = run_package(pkg)
        except Exception as e:
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            _run_lock.release()
        return self._json(200, out)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    srv = Server(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/{PAGE}"
    print(f"rApp console (v4, local) at {url}")
    print("Leave this window open while you use the page; close it (or Ctrl+C) to stop.")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
