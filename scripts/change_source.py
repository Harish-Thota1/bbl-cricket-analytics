#!/usr/bin/env python3
"""
Chrysos POC  ·  stage 1.4  ·  make the source system change, and change badly.

Stands in for a customer lab going about its day. Six kinds of change, plus
a realistic rate of dirty data, so the pipeline has something to catch.

Every run writes a ground-truth file naming exactly which rows it inserted,
updated, deleted and dirtied. That file is how the pipeline gets scored.

    source db.env
    python3 scripts/change_source.py                 one run
    python3 scripts/change_source.py --loop 120      every 2 min until Ctrl+C
    python3 scripts/change_source.py --clean         no defects
"""

from __future__ import annotations
import argparse, json, math, os, random, signal, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    sys.exit("psycopg2 is not installed.  pip install psycopg2-binary")

LOG_DIR = Path("out/change_log")
COLS = ("sample_id", "machine_id", "customer", "element", "value_ppm",
        "uncertainty_ppm", "measure_seconds", "assay_mode", "sample_type",
        "crm_code", "crm_certified_ppm", "below_detection", "started_utc")

# ----------------------------------------------------------------------
#  THE DEFECTS
#
#  Every one of these passes the CHECK constraints on the table. That is
#  the point: constraints catch what you thought of at design time, and
#  everything else walks through and arrives in your pipeline. Which is
#  why the pipeline needs quality gates of its own.
# ----------------------------------------------------------------------
DEFECTS = {
    "null_value":      "value_ppm is NULL. the detector read, the calculation failed.",
    "negative_value":  "value_ppm is negative. background subtraction overshot on a near-blank.",
    "absurd_value":    "value_ppm is 50,000. a decimal place wrong, or a calibration fault.",
    "customer_dirty":  "customer has stray whitespace or case. free-text field, two operators.",
    "future_started":  "started_utc is in the future. a lab PC with its clock wrong.",
    "zero_duration":   "measure_seconds is 0. an aborted measurement that still wrote a row.",
}
DEFECT_KEYS = list(DEFECTS)


def lognormal_ppm(element: str) -> float:
    base = math.exp((sum(random.random() for _ in range(4)) - 2) * 2.0 - 0.7)
    return round(base * (18 if element == "silver" else 1), 4)


def uncertainty(value: float) -> float:
    return round(0.05 * math.sqrt(value) + 0.005, 4)


def below_lod(element: str, value: float) -> bool:
    return value < (1.5 if element == "silver" else 0.02)


def dirty(row: dict, kind: str) -> dict:
    """Apply one defect to a row about to be inserted."""
    if kind == "null_value":
        row["value_ppm"] = None
        row["uncertainty_ppm"] = None
    elif kind == "negative_value":
        row["value_ppm"] = -round(random.uniform(0.01, 0.4), 4)
    elif kind == "absurd_value":
        row["value_ppm"] = 50000.0
        row["uncertainty_ppm"] = 0.0001
    elif kind == "customer_dirty":
        row["customer"] = random.choice([f"{row['customer']} ",
                                         f" {row['customer']}",
                                         row["customer"].lower()])
    elif kind == "future_started":
        row["started_utc"] += timedelta(days=random.randint(1, 3))
    elif kind == "zero_duration":
        row["measure_seconds"] = 0
    return row


# ----------------------------------------------------------------------
def new_samples(cur, n_samples: int, dirty_rate: float) -> tuple[list[int], list[dict]]:
    """(1) Normal arrivals, with a realistic proportion of defects mixed in."""
    cur.execute("SELECT machine_id, customer FROM machine ORDER BY machine_id")
    fleet = cur.fetchall()
    cur.execute("SELECT coalesce(max(measurement_id), 0) FROM assay_measurement")
    hint = cur.fetchone()[0]

    now, rows, planned = datetime.now(timezone.utc), [], []
    for i in range(n_samples):
        machine_id, customer = random.choice(fleet)
        sample_id = f"SMP-NEW-{hint + i + 1:07d}"
        started = now - timedelta(seconds=random.randint(60, 3000))
        for element in ("gold", "silver"):
            v = lognormal_ppm(element)
            row = dict(sample_id=sample_id, machine_id=machine_id,
                       customer=customer, element=element, value_ppm=v,
                       uncertainty_ppm=uncertainty(v),
                       measure_seconds=random.randint(88, 96),
                       assay_mode="gold_tuned", sample_type="customer",
                       crm_code=None, crm_certified_ppm=None,
                       below_detection=below_lod(element, v),
                       started_utc=started)
            defect = None
            if random.random() < dirty_rate:
                defect = random.choice(DEFECT_KEYS)
                row = dirty(row, defect)
            rows.append(tuple(row[c] for c in COLS))
            planned.append({"sample_id": sample_id, "element": element,
                            "defect": defect})

    psycopg2.extras.execute_values(
        cur,
        f"INSERT INTO assay_measurement ({','.join(COLS)}) VALUES %s "
        f"RETURNING measurement_id",
        rows, page_size=500)
    ids = [r[0] for r in cur.fetchall()]

    defects = [{"measurement_id": i, "defect": p["defect"],
                "meaning": DEFECTS[p["defect"]]}
               for i, p in zip(ids, planned) if p["defect"]]
    return ids, defects


def duplicate_key(cur) -> list[int]:
    """(2) DEFECT: the same sample_id and element recorded twice.

    A jar re-keyed after a correction, with both rows kept. There is no
    unique constraint on (sample_id, element), so nothing stops it. Any
    aggregate downstream now double counts that sample.
    """
    cur.execute(
        f"""INSERT INTO assay_measurement ({','.join(COLS)})
            SELECT {','.join(COLS)} FROM assay_measurement
             WHERE sample_type = 'customer' AND value_ppm IS NOT NULL
             ORDER BY random() LIMIT 1
         RETURNING measurement_id, sample_id, element""")
    r = cur.fetchone()
    return [{"measurement_id": r[0], "defect": "duplicate_key",
             "meaning": f"second row for sample {r[1]} / {r[2]}. no unique "
                        f"constraint exists, so aggregates double count it."}]


def recalculate_recent(cur, n: int) -> list[int]:
    """(3) A result recalculated within the last few days."""
    cur.execute(
        """UPDATE assay_measurement AS a
              SET value_ppm       = round(a.value_ppm * 1.04, 4),
                  uncertainty_ppm = round(a.uncertainty_ppm * 1.10, 4)
            WHERE a.measurement_id IN (
                    SELECT measurement_id FROM assay_measurement
                     WHERE started_utc > now() - interval '7 days'
                       AND sample_type = 'customer' AND value_ppm > 0
                     ORDER BY random() LIMIT %s)
          RETURNING a.measurement_id""", (n,))
    return [r[0] for r in cur.fetchall()]


def recalculate_old(cur, n: int) -> list[int]:
    """(4) THE LATE-ARRIVING CORRECTION.

    A measurement from two months ago, corrected today. started_utc is
    still two months old; only updated_at moves. Watermark on the wrong
    column and this correction never reaches you.
    """
    cur.execute(
        """UPDATE assay_measurement AS a
              SET value_ppm       = round(a.value_ppm * 0.88, 4),
                  uncertainty_ppm = round(a.uncertainty_ppm * 1.25, 4)
            WHERE a.measurement_id IN (
                    SELECT measurement_id FROM assay_measurement
                     WHERE started_utc < now() - interval '60 days'
                       AND sample_type = 'customer' AND value_ppm > 0
                     ORDER BY random() LIMIT %s)
          RETURNING a.measurement_id""", (n,))
    return [r[0] for r in cur.fetchall()]


def void_sample(cur) -> list[int]:
    """(5) A jar keyed against the wrong sample id. The lab voids it.

    Both element rows go. No flag, no tombstone. They stop existing.
    """
    cur.execute(
        """DELETE FROM assay_measurement
            WHERE sample_id = (SELECT sample_id FROM assay_measurement
                                WHERE sample_type = 'customer'
                                ORDER BY random() LIMIT 1)
          RETURNING measurement_id""")
    return [r[0] for r in cur.fetchall()]


def retention_purge(cur, n: int) -> list[int]:
    """(6) A retention job removing the oldest rows in one statement."""
    if n <= 0:
        return []
    cur.execute(
        """DELETE FROM assay_measurement
            WHERE measurement_id IN (SELECT measurement_id
                                       FROM assay_measurement
                                      ORDER BY started_utc ASC LIMIT %s)
          RETURNING measurement_id""", (n,))
    return [r[0] for r in cur.fetchall()]


def backdated_insert(cur, lag_minutes: int) -> dict:
    """(7) THE COMMIT-LAG TRAP.

    A row that becomes visible now but carries an updated_at from minutes
    ago, as a transaction that started before your read and committed
    after it would. A load reading strictly after its saved watermark
    never sees this row. Not late. Never. The fix is a look-back window,
    which only works if writing a row twice is harmless.

    It can carry a past updated_at at all because the trigger is on
    UPDATE only, and DEFAULT now() steps aside when a value is given.
    """
    stamp = datetime.now(timezone.utc) - timedelta(minutes=lag_minutes)
    cur.execute("SELECT machine_id, customer FROM machine ORDER BY random() LIMIT 1")
    machine_id, customer = cur.fetchone()
    v = lognormal_ppm("gold")
    cur.execute(
        """INSERT INTO assay_measurement
             (sample_id, machine_id, customer, element, value_ppm,
              uncertainty_ppm, measure_seconds, assay_mode, sample_type,
              below_detection, started_utc, created_at, updated_at)
           VALUES (%s,%s,%s,'gold',%s,%s,92,'gold_tuned','customer',%s,%s,%s,%s)
        RETURNING measurement_id""",
        (f"SMP-LAGGED-{int(stamp.timestamp())}", machine_id, customer, v,
         uncertainty(v), below_lod("gold", v), stamp, stamp, stamp))
    return {"measurement_id": cur.fetchone()[0],
            "updated_at": stamp.isoformat(), "lag_minutes": lag_minutes}


# ----------------------------------------------------------------------
def one_run(conn, args, run_no: int) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT current_database(), inet_server_addr(), count(*) "
                "FROM assay_measurement")
    db, server_ip, before = cur.fetchone()

    rate = 0.0 if args.clean else args.dirty_rate
    inserted, defects = new_samples(cur, args.new_samples, rate)
    if not args.clean:
        defects += duplicate_key(cur)
    upd_recent = recalculate_recent(cur, args.recalc_recent)
    upd_old    = recalculate_old(cur, args.recalc_old)
    voided     = void_sample(cur)
    purged     = retention_purge(cur, args.purge)
    lagged     = backdated_insert(cur, args.lag_minutes)

    cur.execute("SELECT count(*) FROM assay_measurement")
    after = cur.fetchone()[0]
    conn.commit()

    run_at = datetime.now(timezone.utc)
    truth = {"run_at": run_at.isoformat(), "database": db,
             "server_ip": str(server_ip), "rows_before": before,
             "rows_after": after, "inserted_ids": inserted,
             "updated_recent_ids": upd_recent, "updated_old_ids": upd_old,
             "deleted_voided_ids": voided, "deleted_purged_ids": purged,
             "backdated_row": lagged, "dirty_rows": defects}

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = LOG_DIR / f"{run_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(truth, indent=2))

    tag = f"run {run_no}  " if args.loop else ""
    print(f"\n{tag}{db} at {server_ip}   {before:,} rows before")
    print(f"  inserted            {len(inserted):>5}   ({args.new_samples} samples x 2 elements)")
    print(f"  recalculated recent {len(upd_recent):>5}")
    print(f"  recalculated OLD    {len(upd_old):>5}   started_utc 60+ days ago")
    print(f"  voided a sample     {len(voided):>5}   gone, no trace")
    print(f"  retention purge     {len(purged):>5}   gone, no trace")
    print(f"  backdated insert        1   id {lagged['measurement_id']}, "
          f"updated_at = now minus {args.lag_minutes} min")
    if defects:
        counts: dict[str, int] = {}
        for d in defects:
            counts[d["defect"]] = counts.get(d["defect"], 0) + 1
        print(f"  DIRTY ROWS          {len(defects):>5}   "
              + ", ".join(f"{k} x{v}" for k, v in sorted(counts.items())))
    print(f"  {after:,} rows after   (net {after - before:+,})   ground truth {out.name}")
    cur.close()
    return truth


def main() -> int:
    p = argparse.ArgumentParser(description="Make the source system change.")
    p.add_argument("--new-samples",   type=int,   default=60)
    p.add_argument("--recalc-recent", type=int,   default=15)
    p.add_argument("--recalc-old",    type=int,   default=5)
    p.add_argument("--purge",         type=int,   default=40)
    p.add_argument("--lag-minutes",   type=int,   default=4)
    p.add_argument("--dirty-rate",    type=float, default=0.03,
                   help="proportion of new rows given a defect (default 3%%)")
    p.add_argument("--clean",  action="store_true", help="inject no defects")
    p.add_argument("--loop",   type=int, metavar="SECONDS",
                   help="keep running every SECONDS until Ctrl+C")
    p.add_argument("--iterations", type=int, help="stop after N runs")
    p.add_argument("--seed",   type=int, help="fix the randomness")
    args = p.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
    if not os.environ.get("PGHOST"):
        sys.exit("PGHOST is not set. Run 'source db.env' first.")

    conn = psycopg2.connect("")
    conn.autocommit = False

    stop = {"now": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("now", True))

    run_no = 0
    while True:
        run_no += 1
        one_run(conn, args, run_no)
        if not args.loop or stop["now"]:
            break
        if args.iterations and run_no >= args.iterations:
            break
        for _ in range(args.loop):
            if stop["now"]:
                break
            time.sleep(1)
        if stop["now"]:
            print("\nstopped.")
            break

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
