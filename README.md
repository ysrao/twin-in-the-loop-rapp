# Twin-in-the-Loop rApp on a Virtual RIC

**[Run it in Colab](https://colab.research.google.com/github/ysrao/twin-in-the-loop-rapp/blob/main/notebook/rapp_run.ipynb)** &middot; **[Live console page](https://ysrao.github.io/twin-in-the-loop-rapp/rapp-run.html)** &middot; **[Landing page](https://ysrao.github.io/twin-in-the-loop-rapp/)**


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

The study network (a San Francisco 1 km tile, three towers, recorded
counters) and the open city scene are built in. The console page
(`rapp-run.html`) is the advanced path: it builds a run package from your own
sites and counters to paste into the notebook.

Synced with the full description: *Twin-in-the-Loop Optimisation as an rApp
on a Virtual RIC*, v4, Nov 2026. Artefact v2, 16 Nov 2026.

Code: MIT. Scene and data: CC BY 4.0 (city geometry from DataSF Building
Footprints, CC0, and AWS Terrain Tiles).
