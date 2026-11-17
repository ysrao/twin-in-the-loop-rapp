"""A1 check: the rApp's slice and energy decisions as A1 policies, sent to an A1 simulator.

What it shows: each tower's decision can be expressed as an A1 policy that matches
its policy type's JSON schema, an A1 endpoint (O-RAN A1-P v2, the O-RAN SC A1
simulator in STD_2.0.0 mode standing in for a Near-RT RIC) accepts it, returns its
status, and deletes it, and the endpoint rejects a policy that breaks the schema.
What it does not show: any effect on the radio network - the simulator only stores
and acknowledges policies. Capacity, OLLA and P0 changes are O1 configuration
changes, not A1 policies, so they are not part of this check.

Runs the same on Colab and on a Mac (no Docker): on first use it downloads a pinned
commit of the O-RAN SC simulator (github.com/o-ran-sc/sim-a1-interface, Apache-2.0),
installs its Python packages into a folder of their own, and runs it on 127.0.0.1
only, for the length of the check.
"""
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

SIM_REPO = "o-ran-sc/sim-a1-interface"
SIM_COMMIT = "9e15e3f2a879a88b922076451b6dadd4e4e71f45"   # master, 21 Oct 2026
SIM_PACKAGES = ["Flask==2.2.5", "connexion[flask]==2.14.2", "jsonschema", "requests"]
SIM_PORT = 2222          # the simulator's own A1 port (its nginx front end, 8085, is not used)
A1_VERSION = "STD_2.0.0"
A1_BASE = f"http://127.0.0.1:{SIM_PORT}"

# ---- the rApp's policy types (rApp-defined: the A1 standard leaves these to the operator)
SLICE_TYPE = "TWIN_SlicePrbShares_1.0.0"
ENERGY_TYPE = "TWIN_EnergyCarrierSleep_1.0.0"

_STATUS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {"enforceStatus": {"type": "string"}, "enforceReason": {"type": "string"}},
    "required": ["enforceStatus"],
}
_SCOPE = {
    "type": "object",
    "properties": {"cellId": {"type": "string", "pattern": "^[A-Za-z0-9_.:-]+$"}},
    "required": ["cellId"],
    "additionalProperties": False,
}
_SHARE = {"type": "number", "minimum": 0.0, "maximum": 1.0}

POLICY_TYPES = {
    SLICE_TYPE: {
        "policySchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": SLICE_TYPE,
            "description": "PRB shares per slice and the scheduler for one cell (tower), "
                           "as chosen by the twin-in-the-loop rApp's slice / PRB function.",
            "type": "object",
            "properties": {
                "scope": _SCOPE,
                "statement": {
                    "type": "object",
                    "properties": {
                        "profile": {"type": "string"},
                        "prbShares": {
                            "type": "object",
                            "properties": {"embb": _SHARE, "urllc": _SHARE, "mmtc": _SHARE},
                            "required": ["embb", "urllc", "mmtc"],
                            "additionalProperties": False,
                        },
                        "scheduler": {"type": "string"},
                    },
                    "required": ["profile", "prbShares", "scheduler"],
                    "additionalProperties": False,
                },
            },
            "required": ["scope", "statement"],
            "additionalProperties": False,
        },
        "statusSchema": _STATUS_SCHEMA,
    },
    ENERGY_TYPE: {
        "policySchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": ENERGY_TYPE,
            "description": "Carrier sleep in the low-traffic hours for one cell (tower), "
                           "as planned by the twin-in-the-loop rApp's energy function.",
            "type": "object",
            "properties": {
                "scope": _SCOPE,
                "statement": {
                    "type": "object",
                    "properties": {
                        "sleepEnabled": {"type": "boolean"},
                        "carriersToSleep": {"type": "integer", "minimum": 0, "maximum": 8},
                        "carriersKeptOn": {"type": "integer", "minimum": 1, "maximum": 8},
                        "lowTrafficHoursPerNight": {"type": "number", "minimum": 0, "maximum": 24},
                    },
                    "required": ["sleepEnabled", "carriersToSleep", "carriersKeptOn",
                                 "lowTrafficHoursPerNight"],
                    "additionalProperties": False,
                },
            },
            "required": ["scope", "statement"],
            "additionalProperties": False,
        },
        "statusSchema": _STATUS_SCHEMA,
    },
}


def _short(site_id):
    return str(site_id).replace("sf-twin-tower-", "tower-")


def build_policies(result):
    """One A1 policy per tower and function, from the rApp's RESULT (slices / energy)."""
    out = []
    for s in (result.get("slices") or ([result["slice"]] if result.get("slice") else [])):
        prof = next((p for p in s["profiles"] if p["name"] == s["chosen_profile"]), None)
        if prof is None or not s.get("site"):
            continue
        sh = [float(x) for x in prof["shares"]]
        out.append({
            "function": "slice", "site": s["site"], "type": SLICE_TYPE,
            "policy_id": f"twin-slice-{_short(s['site'])}",
            "changed": s["chosen_profile"] != s["current_profile"],
            "body": {"scope": {"cellId": s["site"]},
                     "statement": {"profile": prof["name"],
                                   "prbShares": {"embb": sh[0], "urllc": sh[1], "mmtc": sh[2]},
                                   "scheduler": prof["scheduler"]}}})
    for p in (result.get("energy") or {}).get("per_site", []):
        n = int(p["carriers"])
        sleep = bool(p["sleep"]) and n >= 2
        out.append({
            "function": "energy", "site": p["site"], "type": ENERGY_TYPE,
            "policy_id": f"twin-energy-{_short(p['site'])}",
            "changed": sleep,
            "body": {"scope": {"cellId": p["site"]},
                     "statement": {"sleepEnabled": sleep,
                                   "carriersToSleep": (n - 1) if sleep else 0,
                                   "carriersKeptOn": 1 if sleep else max(n, 1),
                                   "lowTrafficHoursPerNight": float(p["low_hours"]) if sleep else 0.0}}})
    return out


def validate_locally(policies):
    """Schema check on this machine (no simulator needed): {policy_id: None | error text}."""
    from jsonschema import validate
    res = {}
    for p in policies:
        try:
            validate(instance=p["body"], schema=POLICY_TYPES[p["type"]]["policySchema"])
            res[p["policy_id"]] = None
        except Exception as e:  # jsonschema.ValidationError
            res[p["policy_id"]] = str(getattr(e, "message", e))[:200]
    return res


# ---- the simulator: fetch, install, start, stop -------------------------------------------

def _cache_dir():
    return os.environ.get("A1SIM_DIR") or os.path.join(os.path.expanduser("~"), ".cache",
                                                       "twin-rapp-a1sim", SIM_COMMIT[:12])


def _install(target, log):
    """Install the simulator's packages into `target` (pip, else uv, else ensurepip + pip)."""
    tries = [[sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
              "--target", target] + SIM_PACKAGES]
    uv = shutil.which("uv")
    if uv:
        tries.append([uv, "pip", "install", "--quiet", "--python", sys.executable,
                      "--target", target] + SIM_PACKAGES)
    last = ""
    for cmd in tries:
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode == 0:
            return
        last = (p.stderr or p.stdout)[-600:]
    p = subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], capture_output=True, text=True)
    if p.returncode == 0:
        p = subprocess.run(tries[0], capture_output=True, text=True)
        if p.returncode == 0:
            return
        last = (p.stderr or p.stdout)[-600:]
    raise RuntimeError("could not install the A1 simulator's packages: " + last.strip())


def _download(url):
    """Fetch url over HTTPS. Uses certifi's root certificates when installed (a python.org
    Python on macOS ships without any), and falls back to curl."""
    import ssl
    errs = []
    ctxs = []
    try:
        import certifi
        ctxs.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:
        pass
    ctxs.append(ssl.create_default_context())
    for ctx in ctxs:
        try:
            with urllib.request.urlopen(url, timeout=60, context=ctx) as r:
                return r.read()
        except Exception as e:
            errs.append(str(e))
    curl = shutil.which("curl")
    if curl:
        p = subprocess.run([curl, "-fsSL", "--max-time", "120", url], capture_output=True)
        if p.returncode == 0 and p.stdout:
            return p.stdout
        errs.append(p.stderr.decode(errors="replace").strip())
    raise RuntimeError("could not download the A1 simulator (" + "; ".join(errs)[-400:] + ")")


def prepare_simulator(log=print):
    """Download the pinned simulator and its packages once; returns the folder."""
    root = _cache_dir()
    src = os.path.join(root, "near-rt-ric-simulator")
    lib = os.path.join(root, "pylib")
    if not os.path.isfile(os.path.join(src, "src", A1_VERSION, "main.py")):
        os.makedirs(root, exist_ok=True)
        url = f"https://codeload.github.com/{SIM_REPO}/tar.gz/{SIM_COMMIT}"
        log(f"A1 simulator: downloading {SIM_REPO} @ {SIM_COMMIT[:12]} (first use only)")
        data = _download(url)
        prefix = f"sim-a1-interface-{SIM_COMMIT}/near-rt-ric-simulator/"
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            members = []
            for m in tf.getmembers():
                if not m.name.startswith(prefix):
                    continue
                rel = m.name[len(prefix):]
                if not (rel.startswith("src/") or rel.startswith("api/")) or not (m.isfile() or m.isdir()):
                    continue
                m = copy.copy(m)
                m.name = "near-rt-ric-simulator/" + rel
                members.append(m)
            kw = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            tf.extractall(root, members=members, **kw)
    if not os.path.isdir(os.path.join(lib, "connexion")):
        log("A1 simulator: installing its Python packages (first use only, about 20 s)")
        _install(lib, log)
    return root


class Simulator:
    """The A1 simulator (STD_2.0.0) on 127.0.0.1:2222 for the length of a `with` block."""

    def __init__(self, log=print):
        self.log, self.proc, self.out = log, None, None

    def __enter__(self):
        if _get(A1_BASE + "/")[0] == 200:
            raise RuntimeError(f"port {SIM_PORT} is already in use on this machine")
        root = prepare_simulator(self.log)
        sim = os.path.join(root, "near-rt-ric-simulator")
        env = dict(os.environ)
        env["APIPATH"] = os.path.join(sim, "api", A1_VERSION)
        env["PYTHONPATH"] = os.pathsep.join([os.path.join(root, "pylib"), os.path.join(sim, "src", "common")])
        env.pop("EXT_SRV_URL", None); env.pop("KAFKA_DISPATCHER_URL", None)
        self.out = open(os.path.join(root, "simulator.log"), "w")
        self.proc = subprocess.Popen([sys.executable, "-u", "main.py"], cwd=os.path.join(sim, "src", A1_VERSION),
                                     env=env, stdout=self.out, stderr=subprocess.STDOUT)
        for _ in range(60):
            if self.proc.poll() is not None:
                break
            if _get(A1_BASE + "/")[0] == 200:
                return self
            time.sleep(0.25)
        self.__exit__(None, None, None)
        tail = open(os.path.join(root, "simulator.log")).read()[-800:]
        raise RuntimeError("the A1 simulator did not start: " + tail.strip())

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.out:
            self.out.close()
        return False


def _req(method, url, body=None):
    data = None if body is None else json.dumps(body).encode()
    rq = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(rq, timeout=10) as r:
            txt = r.read().decode() or ""
            return r.status, txt
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:  # not reachable
        return None, str(e)


def _get(url):
    return _req("GET", url)


def _json(txt):
    try:
        return json.loads(txt)
    except Exception:
        return None


def run_check(policies, log=print):
    """Load the policy types, then for each policy: create, read back, status, delete;
    plus one policy that breaks the schema, which the endpoint must reject.
    Returns the record the result shows."""
    rec = {"endpoint": f"O-RAN SC A1 simulator ({A1_VERSION}, A1-P v2) @ {SIM_COMMIT[:12]}, "
                       f"127.0.0.1:{SIM_PORT}",
           "policy_types": sorted(POLICY_TYPES), "policies": [], "negative": None}
    v2 = A1_BASE + "/A1-P/v2"
    with Simulator(log):
        _req("POST", A1_BASE + "/deleteall")
        for tid, t in POLICY_TYPES.items():
            code, txt = _req("PUT", f"{A1_BASE}/policytype?id={tid}", t)
            if code not in (200, 201):
                raise RuntimeError(f"loading policy type {tid} failed: HTTP {code} {txt[:200]}")
        listed = _json(_get(v2 + "/policytypes")[1]) or []
        rec["types_listed_by_endpoint"] = listed
        for p in policies:
            url = f"{v2}/policytypes/{p['type']}/policies/{p['policy_id']}"
            r = {"policy_id": p["policy_id"], "type": p["type"], "site": p["site"],
                 "function": p["function"], "changed": p["changed"], "body": p["body"]}
            r["create"], _ = _req("PUT", url, p["body"])
            c, txt = _get(url)
            r["read_back"] = c
            r["read_back_matches"] = (c == 200 and _json(txt) == p["body"])
            c, txt = _get(url + "/status")
            r["status_code"] = c
            st = _json(txt) or {}
            r["status"] = st.get("enforceStatus")
            r["delete"], _ = _req("DELETE", url)
            r["ok"] = (r["create"] == 201 and r["read_back_matches"] and r["status_code"] == 200
                       and r["delete"] == 204)
            rec["policies"].append(r)
        # negative test: a slice policy whose eMBB share is 1.5 (> 1) must be rejected
        bad = {"scope": {"cellId": "sf-twin-tower-B"},
               "statement": {"profile": "invalid", "prbShares": {"embb": 1.5, "urllc": 0.2, "mmtc": 0.2},
                             "scheduler": "pf"}}
        c, _ = _req("PUT", f"{v2}/policytypes/{SLICE_TYPE}/policies/twin-negative-test", bad)
        rec["negative"] = {"what": "slice policy with eMBB share 1.5 (schema allows 0-1)",
                           "http": c, "rejected": c == 400}
        _req("POST", A1_BASE + "/deleteall")
    rec["all_ok"] = bool(rec["policies"]) and all(r["ok"] for r in rec["policies"]) and rec["negative"]["rejected"]
    return rec
