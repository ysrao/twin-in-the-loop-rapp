"""O1 check: the rApp's configuration changes as O1 edits, checked against YANG models.

What it shows: every configuration change the rApp recommends (antenna tilt,
azimuth, transmit power from the capacity function; OLLA offset, MCS cap and
P0 nominal PUSCH from the audit) can be written as an O1 configuration edit
whose every leaf exists in a YANG model and whose value fits that leaf's type
and range. Where 3GPP has a standard attribute (TS 28.541 / 28.662 NR NRM,
Rel-18 YANG from 3GPP Forge) the edit uses it; where it has none (OLLA offset,
MCS cap, P0) the edit uses `twin-rapp-vendor-cm`, a small vendor-style module
in this repository, and is labelled vendor-specific.
What it does not show: a NETCONF exchange with a device, that a real gNB would
accept the edit, or its effect on the network. Each edited leaf is checked on
its own; a whole-device configuration (every mandatory leaf of the cell) would
need the operator's running configuration.

Runs the same on Colab and on a Mac: on first use it downloads pinned YANG
models (3GPP Forge sa5/MnS tag Tag_Rel18_SA113; IETF modules from
github.com/YangModels/yang) and installs yangson, a pure-Python YANG library,
into a folder of their own.
"""
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile

from a1_check import _download

MNS_TAG = "Tag_Rel18_SA113"
MNS_COMMIT = "6e10ac551924bec8747585ed65b8b368afdd311e"           # 17 Sep 2026
MNS_URL = ("https://forge.3gpp.org/rep/api/v4/projects/sa5%2FMnS/repository/"
           f"archive.tar.gz?sha={MNS_COMMIT}&path=yang-models")
IETF_COMMIT = "e13b05c4ddcbfab9170e60dddbbe9eaf6a831964"          # YangModels/yang, 16 Nov 2026
IETF_MODULES = ["ietf-yang-types@2013-07-15", "ietf-inet-types@2013-07-15"]
IETF_URL = "https://raw.githubusercontent.com/YangModels/yang/" + IETF_COMMIT + "/standard/ietf/RFC/{}.yang"
PACKAGES = ["yangson==1.7.9"]
VENDOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yang")
ROOTS = ["_3gpp-eqp-antennafunction", "_3gpp-nr-nrm-commonbeamformingfunction",
         "_3gpp-nr-nrm-nrsectorcarrier", "twin-rapp-vendor-cm"]
DEFAULT_TX_POWER_MW = 40000   # stand-in for a carrier's configuredMaxTxPower (46 dBm); read the real one over O1

ME = "_3gpp-common-managed-element:ManagedElement"
DU = "_3gpp-nr-nrm-gnbdufunction:GNBDUFunction"
SC = "_3gpp-nr-nrm-nrsectorcarrier:NRSectorCarrier"
CBF = "_3gpp-nr-nrm-commonbeamformingfunction:CommonBeamformingFunction"
ANT = "_3gpp-eqp-antennafunction:AntennaFunction"
VCM = "twin-rapp-vendor-cm:vendor-cell-config"

# schema path (no keys) + where it comes from, per rApp parameter
PARAMS = {
    "tilt": {"path": f"/{ME}/{ANT}/attributes/retTiltValue", "leaf": "retTiltValue",
             "model": "3GPP TS 28.541 / 28.662 (AntennaFunction)", "units": "0.1 degree", "standard": True},
    "azimuth": {"path": f"/{ME}/{DU}/{SC}/{CBF}/attributes/digitalAzimuth", "leaf": "digitalAzimuth",
                "model": "3GPP TS 28.541 (CommonBeamformingFunction)", "units": "0.1 degree", "standard": True},
    "power": {"path": f"/{ME}/{DU}/{SC}/attributes/configuredMaxTxPower", "leaf": "configuredMaxTxPower",
              "model": "3GPP TS 28.541 (NRSectorCarrier)", "units": "mW", "standard": True},
    "olla": {"path": f"/{VCM}/cell/olla-offset-db", "leaf": "olla-offset-db",
             "model": "vendor-specific (twin-rapp-vendor-cm)", "units": "dB", "standard": False},
    "mcs_cap": {"path": f"/{VCM}/cell/mcs-cap", "leaf": "mcs-cap",
                "model": "vendor-specific (twin-rapp-vendor-cm)", "units": "MCS index", "standard": False},
    "p0": {"path": f"/{VCM}/cell/p0-nominal-pusch-dbm", "leaf": "p0-nominal-pusch-dbm",
           "model": "vendor-specific (twin-rapp-vendor-cm)", "units": "dBm", "standard": False},
}


def _instance(param, site, sector):
    """A readable instance path (3GPP DN style) for one edit."""
    if param == "tilt":
        return f"ManagedElement={site},AntennaFunction=ant-{sector}/attributes/retTiltValue"
    if param == "azimuth":
        return (f"ManagedElement={site},GNBDUFunction=1,NRSectorCarrier={sector},"
                f"CommonBeamformingFunction=1/attributes/digitalAzimuth")
    if param == "power":
        return f"ManagedElement={site},GNBDUFunction=1,NRSectorCarrier={sector}/attributes/configuredMaxTxPower"
    return f"vendor-cell-config/cell[site-id={site}][sector={sector}]/{PARAMS[param]['leaf']}"


def build_edits(result, tx_power_mw=DEFAULT_TX_POWER_MW):
    """One O1 edit per changed parameter per sector, from the rApp's RESULT."""
    edits = []

    def add(param, site, sector, before, after, value, what):
        p = PARAMS[param]
        edits.append({"param": param, "site": site, "sector": sector, "what": what,
                      "from": before, "to": after, "value": value, "leaf": p["leaf"],
                      "units": p["units"], "model": p["model"], "standard": p["standard"],
                      "schema_path": p["path"], "instance": _instance(param, site, sector)})

    before, after = result.get("configs_before") or {}, result.get("configs_after") or {}
    for site, b in before.items():
        a = after.get(site)
        if not a:
            continue
        for i in range(3):
            tb, ta = float(b["tilts"][i]), float(a["tilts"][i])
            if abs(ta - tb) > 1e-9:
                add("tilt", site, i + 1, round(tb, 2), round(ta, 2), int(round(ta * 10)),
                    f"electrical tilt {tb:g} -> {ta:g} deg")
            ab, aa = float(b["azimuths"][i]), float(a["azimuths"][i])
            if abs(aa - ab) > 1e-9:
                d = (aa - ab + 180.0) % 360.0 - 180.0
                add("azimuth", site, i + 1, round(ab, 1), round(aa, 1), int(round(d * 10)),
                    f"azimuth {ab:g} -> {aa:g} deg, steered {d:+g} deg from boresight")
        pb, pa = float(b.get("power_offset_db", 0.0)), float(a.get("power_offset_db", 0.0))
        if abs(pa - pb) > 1e-9:
            for i in range(3):
                mw_b = int(round(tx_power_mw * 10 ** (pb / 10)))
                mw_a = int(round(tx_power_mw * 10 ** (pa / 10)))
                add("power", site, i + 1, mw_b, mw_a, mw_a,
                    f"transmit power {pb:+g} -> {pa:+g} dB ({mw_b} -> {mw_a} mW on a "
                    f"{tx_power_mw / 1000:g} W stand-in)")
    for c in result.get("cell_changes") or []:
        param = {"olla_offset_db": "olla", "mcs_cap": "mcs_cap", "p0_nominal_pusch_dbm": "p0"}.get(c["param"])
        if not param:
            continue
        v = c["to"]
        # RFC 7951 JSON encodes a decimal64 leaf as a string ("4.00"), integers as numbers
        value = f"{float(v):.2f}" if param == "olla" else int(v)
        add(param, c["site"], int(c["sector"]), c.get("from"), v, value,
            f"{c['param'].replace('_', ' ')} {c.get('from')} -> {v} ({c.get('source', 'audit')})")
    return edits


def edit_documents(edits):
    """The edits as RFC 7951 JSON edit-config documents (merge), one per site."""
    docs = {}
    for e in edits:
        d = docs.setdefault(e["site"], {})
        s = e["sector"]
        if e["standard"]:
            me = d.setdefault(ME, [{"id": e["site"]}])[0]
            if e["param"] == "tilt":
                ants = me.setdefault(ANT, [])
                ant = next((x for x in ants if x["id"] == f"ant-{s}"), None) or ants.append({"id": f"ant-{s}", "attributes": {}}) or ants[-1]
                ant["attributes"]["retTiltValue"] = e["value"]
            else:
                du = me.setdefault(DU, [{"id": "1"}])[0]
                scs = du.setdefault(SC, [])
                sc = next((x for x in scs if x["id"] == str(s)), None) or scs.append({"id": str(s)}) or scs[-1]
                if e["param"] == "power":
                    sc.setdefault("attributes", {})["configuredMaxTxPower"] = e["value"]
                else:
                    sc.setdefault(CBF, [{"id": "1", "attributes": {}}])[0]["attributes"]["digitalAzimuth"] = e["value"]
        else:
            cells = d.setdefault(VCM, {"cell": []})["cell"]
            cell = next((x for x in cells if x["sector"] == s), None) or cells.append({"site-id": e["site"], "sector": s}) or cells[-1]
            cell[e["leaf"]] = e["value"]
    return docs


# ---- models and validator --------------------------------------------------------------

def _cache_dir():
    return os.environ.get("O1_YANG_DIR") or os.path.join(os.path.expanduser("~"), ".cache", "twin-rapp-o1",
                                                         MNS_COMMIT[:12])


def _install(target):
    tries = [[sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
              "--target", target] + PACKAGES]
    uv = shutil.which("uv")
    if uv:
        tries.append([uv, "pip", "install", "--quiet", "--python", sys.executable, "--target", target] + PACKAGES)
    last = ""
    for cmd in tries:
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode == 0:
            return
        last = (p.stderr or p.stdout)[-600:]
    raise RuntimeError("could not install yangson: " + last.strip())


def _meta(text):
    t = re.sub(r"//[^\n]*", "", text)
    return (re.findall(r"^\s*import\s+([\w-]+)", t, re.M),
            (re.search(r"^\s*revision\s+\"?(\d{4}-\d{2}-\d{2})", t, re.M) or [None, ""])[1],
            re.search(r"^\s*namespace\s+\"?([^\";\s]+)", t, re.M).group(1),
            re.findall(r"^\s*feature\s+([\w-]+)", t, re.M))


def prepare(log=print):
    """Download the pinned models and yangson once; returns (cache folder, module set folder)."""
    root = _cache_dir()
    src, lib, mset = (os.path.join(root, x) for x in ("models", "pylib", "moduleset"))
    if not os.path.isfile(os.path.join(src, "_3gpp-nr-nrm-nrsectorcarrier.yang")):
        os.makedirs(src, exist_ok=True)
        log(f"O1 models: downloading 3GPP NR NRM YANG ({MNS_TAG}) and IETF types (first use only)")
        with tarfile.open(fileobj=io.BytesIO(_download(MNS_URL)), mode="r:gz") as tf:
            for m in tf.getmembers():
                if m.isfile() and m.name.endswith(".yang") and "/yang-models/" in m.name:
                    with open(os.path.join(src, os.path.basename(m.name)), "wb") as f:
                        f.write(tf.extractfile(m).read())
        for name in IETF_MODULES:
            with open(os.path.join(src, name + ".yang"), "wb") as f:
                f.write(_download(IETF_URL.format(name)))
    if not os.path.isdir(os.path.join(lib, "yangson")):
        log("O1 models: installing yangson (first use only)")
        _install(lib)
    # the module set: the import closure of the models the edits touch, plus the vendor module
    files = {}
    for d in (src, VENDOR_DIR):
        for f in os.listdir(d):
            if f.endswith(".yang"):
                files[f[:-5].split("@")[0]] = os.path.join(d, f)
    seen, stack = [], list(ROOTS)
    while stack:
        m = stack.pop()
        if m in seen:
            continue
        if m not in files:
            raise RuntimeError(f"YANG module {m} not found")
        seen.append(m)
        stack += _meta(open(files[m]).read())[0]
    shutil.rmtree(mset, ignore_errors=True)
    os.makedirs(mset)
    lib_mods = []
    for m in sorted(seen):
        text = open(files[m]).read()
        _, rev, ns, feats = _meta(text)
        with open(os.path.join(mset, m + (f"@{rev}" if rev else "") + ".yang"), "w") as f:
            f.write(text)
        e = {"name": m, "revision": rev, "namespace": ns, "conformance-type": "implement"}
        if feats:
            e["feature"] = feats
        lib_mods.append(e)
    with open(os.path.join(mset, "yang-library.json"), "w") as f:
        json.dump({"ietf-yang-library:modules-state": {"module-set-id": "twin-rapp-o1", "module": lib_mods}}, f)
    if lib not in sys.path:
        sys.path.insert(0, lib)
    return root, mset, len(lib_mods)


def _check_leaf(dm, schema_path, value):
    node = dm.get_data_node(schema_path)
    if node is None:
        return False, "no such node in the models"
    if not getattr(node, "config", True):
        return False, "read-only (config false)"
    try:
        v = node.type.from_raw(value)
    except Exception as e:
        return False, f"wrong type ({e})"
    if v is None:
        return False, f"wrong type for {type(node.type).__name__}"
    if v not in node.type:
        return False, node.type.error_message or "not allowed by the type"
    return True, type(node.type).__name__.replace("Type", "").lower()


def run_check(edits, log=print):
    """Check every edit's leaf (path exists, writable, value fits its type and range),
    plus two edits that must fail. Returns the record the result shows."""
    root, mset, nmods = prepare(log)
    from yangson import DataModel
    dm = DataModel(open(os.path.join(mset, "yang-library.json")).read(), [mset])
    rec = {"models": f"3GPP NR NRM YANG {MNS_TAG} (Forge sa5/MnS @ {MNS_COMMIT[:12]}) + twin-rapp-vendor-cm, "
                     f"{nmods} modules, checked with yangson",
           "edits": [], "negative": []}
    for e in edits:
        ok, why = _check_leaf(dm, e["schema_path"], e["value"])
        rec["edits"].append(dict(e, ok=ok, check=why))
    for what, path, value in [
            ("antenna tilt of 400 deg (retTiltValue 4000; the model allows 0-3600)", PARAMS["tilt"]["path"], 4000),
            ("P0 nominal PUSCH of -250 dBm (allowed -202 to 24)", PARAMS["p0"]["path"], -250)]:
        ok, why = _check_leaf(dm, path, value)
        rec["negative"].append({"what": what, "rejected": not ok, "reason": why})
    rec["all_ok"] = all(x["ok"] for x in rec["edits"]) and all(n["rejected"] for n in rec["negative"])
    rec["documents"] = edit_documents(edits)
    return rec
