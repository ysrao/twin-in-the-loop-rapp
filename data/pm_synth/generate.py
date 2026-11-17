"""Synthesise dummy PM data for the study towers A, B and C.

Format and value ranges follow an operator's congested-site export
(LTE + 5G NSA cell configuration, daily cell-load KPIs, 18 Aug - 18 Oct 2026).
That export has no BLER, HARQ, rank or power-control counters, so those
columns are synthesised from typical NR ranges, with one planted problem
per tower so the audit has something to find:

  Tower A - link adaptation: DL initial BLER well above the 10 % target,
            high HARQ retransmissions, residual BLER above 1 %.
  Tower B - congestion: PRB utilisation and user throughput in the range of
            the export's congested LTE cells (PRB 67-100 %, 7-14 Mbps).
  Tower C - uplink power control and MIMO: many power-limited UEs
            (negative PHR), high UL BLER, and mostly rank 1 on a 4x4 cell.

No real site names, IDs or coordinates are used. Run:  python3 generate.py
"""
import csv, datetime, math, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
rnd = random.Random(20261018)
DAYS = [datetime.date(2026, 8, 18) + datetime.timedelta(d) for d in range(62)]

# Study towers: azimuths / tilts as in the twin's study network.
TOWERS = {
    "A": {"az": [90, 210, 330], "tilt": [7.9, 6.45, 10.0], "h": 30},
    "B": {"az": [90, 210, 330], "tilt": [10.0, 0.97, 3.92], "h": 30},
    "C": {"az": [90, 210, 330], "tilt": [7.59, 7.68, 3.23], "h": 30},
}


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def g(mu, sd):
    return rnd.gauss(mu, sd)


def write(name, header, rows):
    with open(os.path.join(HERE, name), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"{name}: {len(rows)} rows")


# ---- 1. cell configuration (column style of the export's 5G sheet) --------
cfg_hdr = ["site_id", "sector", "cell_name", "technology", "duplex", "frequency_band",
           "bandwidth_mhz", "antenna_name", "mimo_layers_max", "azimuth_deg",
           "electrical_tilt_deg", "mechanical_tilt_deg", "total_downtilt_deg",
           "eirp_dbm_per_port", "eirp_combined_mimo_dbm", "height_agl_m",
           "dl_bler_target_pct", "p0_nominal_pusch_dbm", "pusch_alpha"]
cfg = []
for t, v in TOWERS.items():
    for s in range(3):
        p0 = -96 if t == "C" else -104          # C: P0 set too high (planted)
        cfg.append([f"sf-twin-tower-{t}", s + 1, f"NR_SF_TWIN_{t}_{s + 1}", "5G NR", "TDD",
                    "n78 (3.6 GHz)", 100, "065_17_XPB_3500_4_GENERIC", 4, v["az"][s],
                    v["tilt"][s], 0, v["tilt"][s], 27.3, 36.3, v["h"], 10, p0, 0.8])
write("site_config.csv", cfg_hdr, cfg)

# ---- 2. daily PM counters per cell ----------------------------------------
pm_hdr = ["date", "site_id", "sector", "cell_name",
          # load (ranges from the export's cell-load KPIs)
          "prb_util_dl_pct", "active_users_avg", "user_dl_tput_mbps", "cell_congested",
          # link adaptation / BLER / HARQ
          "avg_cqi", "avg_dl_mcs", "dl_bler_initial_pct", "dl_bler_residual_pct",
          "harq_dl_retx_rate_pct", "harq_dl_avg_tx", "ul_bler_initial_pct",
          # MIMO
          "dl_rank1_pct", "dl_rank2_pct", "dl_rank3_pct", "dl_rank4_pct", "dl_avg_rank",
          # uplink power control
          "ul_sinr_avg_db", "ul_phr_avg_db", "ul_phr_negative_pct", "pusch_tx_power_avg_dbm"]
pm = []
for day in DAYS:
    wk = 0.92 if day.weekday() >= 5 else 1.0            # weekend dip
    trend = 1 + 0.06 * (day - DAYS[0]).days / len(DAYS)  # load grows over the window
    for t in TOWERS:
        for s in range(1, 4):
            hot = (s == 2)                                 # the planted problem is strongest on sector 2
            # load
            if t == "B":
                prb = clip(g(84, 7) * wk * trend + (5 if hot else 0), 60, 100)
                tput = clip(g(9.2, 1.4) * (100 / max(prb, 60)) * 0.9, 6.5, 14)
                users = g(24, 4) * wk * trend
            else:
                prb = clip(g(55, 10) * wk * trend, 22, 75)
                tput = clip(g(24, 6) * (60 / max(prb, 25)) ** 0.5, 12, 56)
                users = g(11, 3) * wk * trend
            cong = 1 if prb >= 85 else 0
            # BLER / HARQ
            if t == "A":
                bler = clip(g(21 if hot else 16, 2.5), 11, 30)
                resid = clip(g(2.2 if hot else 1.4, 0.4), 0.6, 4)
                cqi = clip(g(8.6, 0.5), 6, 11)
            else:
                bler = clip(g(10.2 if t == "B" else 9.8, 1.0), 7, 13)
                resid = clip(g(0.35, 0.1), 0.1, 0.8)
                cqi = clip(g(10.4 if t == "B" else 11.2, 0.5), 8, 13)
            mcs = clip(cqi * 1.75 + g(0, 0.6), 4, 27)
            retx = bler * (1 + bler / 100)                 # retransmissions incl. second attempts
            avg_tx = 1 + bler / 100 + (bler / 100) ** 2 * 0.6
            # uplink power control
            if t == "C":
                neg = clip(g(41 if hot else 33, 4), 20, 60)
                phr = g(1.5 if hot else 3.5, 1.2)
                ul_sinr = g(4.5 if hot else 6.0, 1.0)
                ul_bler = clip(g(17 if hot else 14, 2), 9, 28)
                ptx = clip(g(19.5, 1.2), 14, 23)
            else:
                neg = clip(g(9, 3), 2, 18)
                phr = g(14, 2.5)
                ul_sinr = g(11, 1.5)
                ul_bler = clip(g(9.5, 1.2), 6, 13)
                ptx = clip(g(9, 2), 2, 16)
            # MIMO rank distribution
            if t == "C":
                r = [g(68 if hot else 58, 4), g(24, 3), g(5, 1.5), g(3, 1)]
            elif t == "B":
                r = [g(30, 4), g(42, 4), g(16, 3), g(12, 2)]
            else:
                r = [g(26, 4), g(40, 4), g(19, 3), g(15, 3)]
            r = [max(0.5, x) for x in r]
            tot = sum(r)
            r = [100 * x / tot for x in r]
            avg_rank = sum((i + 1) * x for i, x in enumerate(r)) / 100
            pm.append([day.isoformat(), f"sf-twin-tower-{t}", s, f"NR_SF_TWIN_{t}_{s}",
                       round(prb, 2), round(max(users, 1), 1), round(tput, 2), cong,
                       round(cqi, 1), round(mcs, 1), round(bler, 2), round(resid, 2),
                       round(retx, 2), round(avg_tx, 3), round(ul_bler, 2),
                       *[round(x, 1) for x in r], round(avg_rank, 2),
                       round(ul_sinr, 1), round(phr, 1), round(neg, 1), round(ptx, 1)])
write("pm_daily_counters.csv", pm_hdr, pm)
