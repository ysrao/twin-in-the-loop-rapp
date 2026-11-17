# Twin-in-the-Loop rApp on a Virtual RIC

**[Run it in Colab](https://colab.research.google.com/github/ysrao/twin-in-the-loop-rapp/blob/main/notebook/rapp_run.ipynb)** &middot; **[Live console page](https://ysrao.github.io/twin-in-the-loop-rapp/rapp-run.html)** &middot; **[Landing page](https://ysrao.github.io/twin-in-the-loop-rapp/)**

**[v4 - Mac run, results saved](https://github.com/ysrao/twin-in-the-loop-rapp/blob/main/notebook/rapp_run_v4_mac.ipynb)** (`notebook/rapp_run_v4_mac.ipynb`: the notebook as run on an Apple M3 GPU, MODE single, FUNCTION all, with every cell's output and the result in the last cell; [open in Colab](https://colab.research.google.com/github/ysrao/twin-in-the-loop-rapp/blob/main/notebook/rapp_run_v4_mac.ipynb))


Twin-gated RAN optimisation as an rApp on a standalone Virtual RIC (a software
Non-RT RIC and its rApps running outside an SMO, connected to the RAN/OSS over
open interfaces). A Sionna RT digital twin scores every candidate change
before it is recommended; nothing reaches the network ungated.

**Functions** (each behind the twin gate): capacity (azimuth / tilt / power,
single tower or cluster), slice PRB shares (single-step PPO, guarded
acceptance), energy (carrier sleep in low-traffic hours), and an audit: the
MCS / OLLA check that recovers the gNB's effective link-adaptation offset from
its MCS histograms, plus counter-based link checks (BLER / HARQ, MIMO rank, UL
power control, load) on the daily PM counters.

**Per tower.** In a cluster run each tower is judged by its own inputs: its
radio configuration, its MCS histograms, its link counters and its network
counters (`counters_by_site` in the run package). Slice picks a profile per
tower, SYS-scored at that tower's offered load; energy plans carrier sleep per
tower, and a tower at 85 % PRB use or more, or congested on 30 % of days or
more in its link counters, keeps every carrier on. The built-in study counters
are per tower: Tower B the recorded ones, Towers A and C dummy values.

## Run it

Open `notebook/rapp_run.ipynb` (Colab button on the landing page, or Jupyter
locally). Change the three settings at the top of the settings cell and Run
all; the result prints in the last cell:

- `MODE` - "single" (one tower) or "cluster" (Towers A + B + C)
- `SITE` - single mode only: "A", "B" or "C" (default "B")
- `FUNCTION` - "capacity", "slice", "energy", "audit" or "all"
- `COUNTER_SET` - "study", "test1", "test2", "test3", or "operator" (your own
  counter dump, edited into `OPERATOR_COUNTERS`)

### On a Mac (Apple-silicon GPU)

Sionna RT ray-traces on the Apple GPU through Mitsuba's Metal backend (the
notebook prints `ray tracing on: Apple GPU (Metal)`). Run it from a clone of
this repository, so it uses the clone's modules and scene:

```bash
git clone https://github.com/ysrao/twin-in-the-loop-rapp.git
cd twin-in-the-loop-rapp
python3 -m venv .venv && source .venv/bin/activate
pip install "sionna-rt==2.2.0" "sionna==2.2.0" trimesh rtree matplotlib jupyter
jupyter notebook notebook/rapp_run.ipynb
```

Python 3.11 or newer. On an M3 a full `FUNCTION = "all"` run takes about
15 s (about 1 s per tower trace).

**Console page with a Run button (local only).** `rapp-run-local.html` is the
console page with a *Run on this Mac* button: it sends the run package to a
small local runner (`local/rapp_server.py`), which executes the notebook with
it and draws the result - changes, before/after numbers, maps, slice, audit
and energy tables - at the bottom of the page. Start it with
`.venv/bin/python local/rapp_server.py` (it opens
`http://127.0.0.1:8765/rapp-run-local.html`). It listens on this Mac only.

The study network (a San Francisco 1 km tile, three towers, recorded
counters) and the open city scene are built in.

### A1 check (O-RAN SC A1 simulator)

With `A1_CHECK = True` (the default) and a slice, energy or all run, each
tower's slice profile and carrier-sleep plan is written as an A1 policy
(rApp-defined policy types `TWIN_SlicePrbShares_1.0.0` and
`TWIN_EnergyCarrierSleep_1.0.0`, in `rapp/a1_check.py`) and:

1. checked against its type's JSON schema on the machine running the notebook;
2. sent over A1-P v2 to the [O-RAN SC A1 simulator](https://docs.o-ran-sc.org/projects/o-ran-sc-sim-a1-interface/en/latest/)
   (STD_2.0.0), standing in for a Near-RT RIC: create (201), read back (200,
   unchanged), status (200), delete (204), plus one invalid policy (an eMBB share
   of 1.5) that the simulator must reject (400).

The notebook sets the simulator up itself, the same way on Colab and on a Mac,
with no Docker: on first use it downloads a pinned commit of
[o-ran-sc/sim-a1-interface](https://github.com/o-ran-sc/sim-a1-interface)
(Apache-2.0), installs Flask 2.2.5 and connexion 2.14.2 into a folder of their
own (`~/.cache/twin-rapp-a1sim`), and runs it on 127.0.0.1:2222 only for the
length of the check. This shows the decisions are well-formed A1 policies an A1
endpoint accepts; it says nothing about their effect on the network (the
simulator only stores policies, so their status stays NOT_ENFORCED). Capacity,
OLLA and P0 changes are O1 configuration changes and are not part of this check.

### O1 check (configuration changes against YANG)

With `O1_CHECK = True` (the default) and a capacity, audit or all run, each
recommended configuration change is written as an O1 edit (RFC 7951 JSON,
merge) and every edited leaf is checked: it must exist in the YANG models, be
writable, and its value must fit the leaf's type and range. Two out-of-range
edits (a 400 deg tilt, a P0 of -250 dBm) must be rejected. Code:
`rapp/o1_check.py`.

| rApp change | O1 attribute | Model |
|---|---|---|
| Electrical tilt | `AntennaFunction/attributes/retTiltValue` (0.1 deg) | 3GPP TS 28.541 / 28.662 |
| Azimuth | `NRSectorCarrier/CommonBeamformingFunction/attributes/digitalAzimuth` (0.1 deg from boresight) | 3GPP TS 28.541 |
| Transmit power | `NRSectorCarrier/attributes/configuredMaxTxPower` (mW, on a 40 W stand-in) | 3GPP TS 28.541 |
| OLLA offset, MCS cap, P0 nominal PUSCH | `vendor-cell-config/cell/...` | `rapp/yang/twin-rapp-vendor-cm` (3GPP has no attribute) |

The 3GPP models are the Rel-18 NR NRM YANG from 3GPP Forge (`sa5/MnS`, tag
`Tag_Rel18_SA113`), with two IETF type modules from YangModels; the check uses
yangson, a pure-Python YANG library. Like the A1 check, the notebook downloads
the pinned models and installs yangson into a folder of their own
(`~/.cache/twin-rapp-o1`) on first use, the same on Colab and a Mac. This shows
the edits are well-formed against the models; it is not a NETCONF exchange
with a device, and it says nothing about a real gNB accepting them. Note that
the 3GPP model gives `configuredMaxTxPower` no range (plain int32, mW).

### The console page: Run on my Mac or Run on Colab

The [console page](https://ysrao.github.io/twin-in-the-loop-rapp/rapp-run.html)
(`rapp-run.html`) is where you choose the run: single tower (A, B or C) or
cluster, the counter set for each tower (study, test counters 1-4, or your own
CSV), and the function. Then press one of its two buttons; the same choice
gives the same result on either:

- **Run on my Mac** - start the local runner first (`.venv/bin/python
  local/rapp_server.py`, or the Desktop launcher). The button opens the local
  page with the run package in the link (it never leaves the Mac); the run
  starts by itself and the result shows there.
- **Run on Colab** - copies the run package and opens the notebook on Colab.
  Click the package cell (it starts `PACKAGE_JSON`), select all, paste, then
  Runtime > Run all. The result prints in the last cell.

## Test data

Everything in `data/` is test data, kept so any run can be repeated and give
the same result. All results in the A1 and O1 test reports (below) were made with it.
None of it is live network data, and only Tower B's MCS histogram comes from a
recording; the rest is made up. Results for Towers A and C show the method
working, not findings about real cells.

| File | What it is | Source | Used by |
|---|---|---|---|
| `counters/counters_busy_hour_congested.csv` | Counter scenario: busy hour, congested (PRB 94 %) | Made up | Test counters 1 on the console page |
| `counters/counters_night_low_load.csv` | Counter scenario: night, low load (PRB 18 %) | Made up | Test counters 2 |
| `counters/counters_edge_coverage_hole.csv` | Counter scenario: weak cell edge (RSRP -108 dBm) | Made up | Test counters 3 |
| `counters/counters_urllc_heavy_slice.csv` | Counter scenario: URLLC-heavy slice mix | Made up | Test counters 4 |
| `test_pm_mcs.csv` | MCS histogram per sector, Tower B | Recorded | MCS audit |
| `test_pm_mcs_tower_A.csv`, `test_pm_mcs_tower_C.csv` | MCS histograms, Towers A and C | Dummy | MCS audit |
| `test_pm_mcs_all_towers.csv` | The three histograms above in one file | Combined | MCS audit, cluster runs |
| `pm_synth/pm_daily_counters.csv` | 62 days of daily cell KPIs (PRB, BLER, HARQ, rank, PHR) for Towers A, B, C | Synthetic, from `pm_synth/generate.py` | Energy congestion guard, BLER link audit |
| `pm_synth/site_config.csv` | Cell configuration (azimuth, tilt, EIRP, P0) for the same cells | Synthetic | Link audit |

Notes:

- The four counter scenarios are also built into both pages, so the console
  works without the files. Change a file and the page copy together.
- The "study" counter set on the console page, one set per tower, is written
  in the notebook (`STUDY_COUNTERS_BY_SITE`). Tower B's are the recorded
  counters; Towers A and C use set values.
- `pm_synth/generate.py` plants one problem per tower so the audits have
  something to find: link adaptation on A, congestion on B, uplink power and
  rank on C. It uses a fixed seed; run `python3 generate.py` to rebuild the
  same files.
- No real site names, IDs or coordinates are used.

**Using real data:** don't overwrite these files. Upload your own CSV on the
console page (the PM MCS-histogram box, or "your own CSV" for counters), or set
`PM_CSV = "../data/<file>.csv"` in the notebook. Give real files distinct names,
such as `pm_mcs_<site>_<date>.csv`. After any code change, rerun with the test
data and compare with the test reports (for example, single Tower B gives 14 O1
edits and 2 A1 policies). A changed number means the code changed a result.

## Test reports

Results of the interface checks, run on a Mac on 17 Nov 2026 with the test data
above, single towers first, then the cluster. Each report is in PDF (reads on
GitHub) and Word.

| Report | What it covers | Files |
|---|---|---|
| A1 interface test | The rApp's slice and energy policies sent to the O-RAN SC A1 simulator (A1-P v2): create, read back, status, delete, plus an invalid policy that must be rejected | [PDF](docs/test-reports/A1-interface-test-report.pdf) · [Word](docs/test-reports/A1-interface-test-report.docx) |
| O1 interface test | The rApp's cell changes as O1 edits, checked against the 3GPP Rel-18 NR NRM YANG and a vendor stand-in module, plus two invalid edits that must be rejected | [PDF](docs/test-reports/O1-interface-test-report.pdf) · [Word](docs/test-reports/O1-interface-test-report.docx) |

Neither check runs on Colab yet, and neither involves a live network element;
each report's limits section says what it does not prove.

Synced with the full description: *Twin-in-the-Loop Optimisation as an rApp
on a Virtual RIC*, v4, Nov 2026. Artefact v4, 17 Nov 2026.

Code: MIT. Scene and data: CC BY 4.0 (city geometry from DataSF Building
Footprints, CC0, and AWS Terrain Tiles).
