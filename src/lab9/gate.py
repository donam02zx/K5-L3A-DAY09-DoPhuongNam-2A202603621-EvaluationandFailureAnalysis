"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    pr_rows, base_rows = pr.get("rows") or [], base.get("rows") or []
    graded = _graded_metrics(spec, base_rows or pr_rows)

    # 1. Metric values must be real numbers: NaN compares False against any floor and slips through.
    for name, rep in (("PR", pr), ("baseline", base)):
        for k, v in (rep.get("metrics") or {}).items():
            if isinstance(v, float) and not math.isfinite(v):
                problems.append(f"{name} metric {k} is {v} (NaN/inf hides a crashed or empty grader)")
    for m in spec.get("metrics", []):
        if m.get("blocking") and m["id"] in graded and (pr.get("metrics") or {}).get(m["id"]) is None:
            problems.append(f"blocking metric {m['id']} has no value in the PR report")

    # 2. Grader crashes: listed failures, or a graded cell that is None / not a bool.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s) in the PR run, "
                        f"first: {str(pr['evaluator_failures'][0])[:80]}")
    if base.get("evaluator_failures"):
        problems.append("baseline has evaluator failures: it cannot be trusted as a reference")
    bad_cells = [(r.get("item_id"), r.get("seed"), m) for r in pr_rows for m in graded
                 if not isinstance(r.get(m), bool)]
    if bad_cells:
        problems.append(f"{len(bad_cells)} graded cell(s) are None/non-bool (crashed grader dropped "
                        f"from the mean), first: {bad_cells[0]}")

    # 3. Coverage: the PR must grade exactly the baseline's (item, seed) grid, once each.
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}
    want_rows = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(pr_rows) != want_rows:
        problems.append(f"{len(pr_rows)} rows but manifest says {man.get('items')} items x "
                        f"{len(man.get('seeds') or [])} seeds = {want_rows} (dropped or duplicated rows)")
    for key in ("items", "seeds"):
        if bman and man.get(key) != bman.get(key):
            problems.append(f"manifest {key} {man.get(key)} != baseline {bman.get(key)}")
    keys = [(r.get("item_id"), r.get("seed")) for r in pr_rows]
    dup = len(keys) - len(set(keys))
    if dup:
        problems.append(f"{dup} duplicated (item, seed) row(s)")
    pk, bk = set(keys), {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if pk != bk:
        problems.append(f"(item, seed) grid differs from baseline: {len(bk - pk)} missing, "
                        f"{len(pk - bk)} extra (cherry-picked seeds or items)")

    # 4. Reported metrics must be what the rows say (hand-edited number, or rows edited after
    #    aggregation). Recomputed with the same aggregate() the harness uses.
    problems += _recompute_mismatch(pr, spec, graded)

    # 5. Slice tags are label-derived; an item may not leave the slice it had on the baseline.
    base_tags = {r.get("item_id"): sorted(r.get("slices") or []) for r in base_rows}
    moved = sorted({r.get("item_id") for r in pr_rows if r.get("item_id") in base_tags
                    and sorted(r.get("slices") or []) != base_tags[r.get("item_id")]})
    if moved:
        problems.append(f"slice tags differ from baseline for {len(moved)} item(s), first: {moved[0]}")

    # 6. Ratchet: on the same eval-set version the spec may only get stricter.
    if base_spec is not None:
        problems += ratchet(spec, base_spec)
    return problems


def _graded_metrics(spec: dict, rows: list[dict]) -> list[str]:
    """Spec metrics that are per-row grader verdicts (present in the rows or registered as graders)."""
    from lab9.graders import GRADERS
    in_rows = set().union(*(r.keys() for r in rows)) if rows else set()
    return [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS or m["id"] in in_rows]


def _recompute_mismatch(pr: dict, spec: dict, graded: list[str]) -> list[str]:
    from lab9.eval import aggregate
    rows = pr.get("rows") or []
    if not rows or any(not isinstance(r.get(m), bool) for r in rows for m in graded):
        return []                                   # already reported as crashed cells
    has_cost = all("cost" in r for r in rows)
    calc = aggregate([{**r, "cost": float(r.get("cost") or 0.0)} for r in rows], graded,
                     k_values=spec.get("pass_k", []))
    out = []
    for k, v in (pr.get("metrics") or {}).items():
        if k not in calc or (k == "cost_per_success" and not has_cost):
            continue
        c = calc[k]
        if isinstance(v, float) and not math.isfinite(v):
            continue                                # reported in step 1
        if (c is None) != (v is None) or (c is not None and abs(float(c) - float(v)) > 1e-3):
            out.append(f"metric {k} reported {v} but its rows give {c} (edited report)")
    return out


def _looser(th: dict, bth: dict) -> list[str]:
    """How threshold th is looser than the baseline threshold bth (empty = same or stricter)."""
    out = []
    for key in ("max", "max_increase"):
        if key in bth and (key not in th or th[key] > bth[key]):
            out.append(f"{key} {bth[key]} -> {th.get(key, 'removed')}")
    if "min" in bth and ("min" not in th or th["min"] < bth["min"]):
        out.append(f"min {bth['min']} -> {th.get('min', 'removed')}")
    if bth.get("no_significant_drop") and not th.get("no_significant_drop"):
        out.append("no_significant_drop removed")
    return out


def ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => every threshold, blocking flag, metric and slice may only get stricter."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []                                   # new eval set => new baseline, thresholds restart
    out = []
    for key in ("eval_set", "labels", "adversarial_pack"):
        if base_spec.get(key) != spec.get(key):
            out.append(f"RATCHET {key} changed {base_spec.get(key)!r} -> {spec.get(key)!r} on the same version")
    if set(base_spec.get("seeds") or []) - set(spec.get("seeds") or []):
        out.append(f"RATCHET seeds reduced {base_spec.get('seeds')} -> {spec.get('seeds')}")
    bb, sb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if (sb.get("confidence", 0.95) > bb.get("confidence", 0.95)
            or sb.get("method", "percentile") != bb.get("method", "percentile")):
        out.append(f"RATCHET bootstrap changed {bb} -> {sb}")
    cur = {m["id"]: m for m in spec.get("metrics", [])}
    for bm in base_spec.get("metrics", []):
        m = cur.get(bm["id"])
        if m is None:
            out.append(f"RATCHET metric {bm['id']} removed")
            continue
        if bm.get("blocking") and not m.get("blocking"):
            out.append(f"RATCHET metric {bm['id']} no longer blocking")
        out += [f"RATCHET metric {bm['id']} {d}"
                for d in _looser(m.get("threshold") or {}, bm.get("threshold") or {})]
    cur_sl = {(x["name"], x["metric"]): x for x in spec.get("slices") or []}
    for bs in base_spec.get("slices") or []:
        sl = cur_sl.get((bs["name"], bs["metric"]))
        sid = f"slice:{bs['name']}/{bs['metric']}"
        if sl is None:
            out.append(f"RATCHET {sid} removed")
            continue
        if bs.get("blocking") and not sl.get("blocking"):
            out.append(f"RATCHET {sid} no longer blocking")
        out += [f"RATCHET {sid} {d}" for d in _looser(sl, bs)]
    if set(base_spec.get("pass_k") or []) - set(spec.get("pass_k") or []):
        out.append(f"RATCHET pass_k reduced {base_spec.get('pass_k')} -> {spec.get('pass_k')}")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a = per_item(pr, metric, slice_name=name)
        b = per_item(base, metric, slice_name=name)
        value = round(sum(a.values()) / len(a), 4) if a else None
        verdict, note = "ok", f"n={len(a)} item"
        if value is None:
            verdict = "missing"                      # an empty slice is a relabelling, not a pass
        else:
            if "min" in sl and value < sl["min"]:
                verdict = "fail"
            if "max" in sl and value > sl["max"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027))
                    note += f" Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<38} {value!s:<8} {json.dumps(th):<40} {note:<36} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
