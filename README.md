# Twin-in-the-Loop rApp on a Virtual RIC

**[Run it in Colab](https://colab.research.google.com/github/ysrao/twin-in-the-loop-rapp/blob/main/notebook/rapp_run.ipynb)** &middot; **[Live console page](https://ysrao.github.io/twin-in-the-loop-rapp/rapp-run.html)** &middot; **[Landing page](https://ysrao.github.io/twin-in-the-loop-rapp/)**

**[v4 - Mac run, results saved](https://github.com/ysrao/twin-in-the-loop-rapp/blob/main/notebook/rapp_run_v4_mac.ipynb)** (`notebook/rapp_run_v4_mac.ipynb`: the notebook as run on an Apple M3 GPU, MODE single, FUNCTION all, with every cell's output and the result in the last cell; [open in Colab](https://colab.research.google.com/github/ysrao/twin-in-the-loop-rapp/blob/main/notebook/rapp_run_v4_mac.ipynb))


Twin-gated RAN optimisation as an rApp on a standalone Virtual RIC (a software
Non-RT RIC and its rApps running outside an SMO, connected to the RAN/OSS over
open interfaces). A Sionna RT digital twin scores every candidate change
before it is recommended; nothing reaches the network ungated.

**Functions** (each behind the twin gate): capacity (azimuth / tilt / power,
single tower or cluster), slice PRB shares (single-step PPO, guarded
acceptance), energy (carrier sleep in low-traffic hours), and an MCS / OLLA
audit that recovers the gNB's effective link-adaptation offset from its MCS
histograms.

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
counters) and the open city scene are built in. The console page
(`rapp-run.html`) is the advanced path: it builds a run package from your own
sites and counters to paste into the notebook.

Synced with the full description: *Twin-in-the-Loop Optimisation as an rApp
on a Virtual RIC*, v4, Nov 2026. Artefact v2, 16 Nov 2026.

Code: MIT. Scene and data: CC BY 4.0 (city geometry from DataSF Building
Footprints, CC0, and AWS Terrain Tiles).
