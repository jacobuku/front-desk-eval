"""CLI: validate / run / show.

    .venv/bin/python -m evalkit.cli validate
    .venv/bin/python -m evalkit.cli run --repeats 3
    .venv/bin/python -m evalkit.cli show [RUN_ID]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from . import config as C
from . import goldens, judge, loader, rubric, runner
from .schema import FatalRunError
from .store import RunStore, latest_run_id, new_run_id

MARK = {"pass": "PASS", "fail": "FAIL", "no_evidence": "NOEV",
        "sut_error": "ERR ", "mixed": "MIX ", "disputed": "DISP", "-": "  - "}


def _load_dotenv() -> None:
    env = C.ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _validate(args) -> int:
    personas, scenarios, default, deferrals, problems = loader.load_all()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        problems.append("ANTHROPIC_API_KEY is not set (.env or environment)")
    if problems:
        print(f"Layer 0 FAILED - {len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"Layer 0 ok: {len(personas)} personas, {len(scenarios)} scenarios, default={default}")
    for pid, checks in sorted(deferrals.items()):
        for name in checks:
            print(f"  deferred to Layer 3: {pid}.{name}")
    for sid, s in scenarios.items():
        print(f"  {sid:<14} {s.model}  thinking={s.thinking}  system={len(s.system)} chars")
    return 0


def _select(args):
    personas, scenarios, default, deferrals, problems = loader.load_all()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        problems.append("ANTHROPIC_API_KEY is not set (.env or environment)")
    if problems:
        print("Layer 0 FAILED - refusing to run on bad input:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        raise SystemExit(1)

    sid = args.scenario or default
    if sid not in scenarios:
        print(f"unknown scenario {sid!r}; known: {', '.join(scenarios)}", file=sys.stderr)
        raise SystemExit(1)
    if args.personas:
        wanted = {p.strip() for p in args.personas.split(",") if p.strip()}
        unknown = wanted - {p.id for p in personas}
        if unknown:
            print(f"unknown persona ids: {', '.join(sorted(unknown))}", file=sys.stderr)
            raise SystemExit(1)
        personas = [p for p in personas if p.id in wanted]
    return personas, scenarios[sid], deferrals


def _run(args) -> int:
    personas, scenario, deferrals = _select(args)
    units = len(personas) * args.repeats
    resume = bool(args.resume)
    run_id = args.resume or new_run_id()

    print(f"run {run_id}  scenario={scenario.id}  model={scenario.model}  "
          f"{len(personas)} personas x {args.repeats} repeats = {units} units  "
          f"concurrency={args.concurrency}")
    if args.dry_run:
        store_dir = C.RUNS_DIR / run_id
        for u in runner.build_units(personas, scenario, args.repeats):
            print(f"  {u.unit_id}")
        print(f"dry run - no API calls. Would write to {store_dir}")
        return 0

    store = RunStore(run_id)
    try:
        summary = asyncio.run(runner.run(
            personas, scenario,
            repeats=args.repeats,
            concurrency=args.concurrency,
            store=store,
            resume=resume,
            deferrals=deferrals,
            do_preflight=not args.no_preflight,
        ))
    except FatalRunError as e:
        print(f"\nABORTED - {e}", file=sys.stderr)
        print("Nothing about this is per-unit; fix the config and re-run.", file=sys.stderr)
        return 2

    _print_summary(summary)
    print(f"\ntranscripts: {store.units_dir}")
    print(f"summary:     {store.summary_path}")
    return 0


def _print_summary(summary: dict) -> None:
    t = summary["totals"]
    print(f"\n{summary['run_id']}  scenario={summary['scenario_id']}  units={summary['unit_count']}")
    print(f"  pass {t['pass']}   fail {t['fail']}   no_evidence {t['no_evidence']}   "
          f"sut_error {t['sut_error']}   truncated {t['truncated']}   "
          f"deferred checks {t.get('deferred_checks', 0)}")

    print("\n  persona  type                repeats            verdict   failed checks")
    for pid, entry in sorted(summary["by_persona"].items()):
        grid = " ".join(MARK[r] for r in entry["results"])
        flag = "" if entry["stable"] else "  <- unstable"
        notes = list(entry["failed_checks"])
        notes += [f"{n} (->L3)" for n in entry.get("deferred_checks", [])]
        print(f"  {pid:<8} {entry['persona_type']:<18}  {grid:<18} {MARK[entry['verdict']]}"
              f"      {', '.join(notes)}{flag}")

    if summary["check_failures"]:
        print("\n  check failures:", ", ".join(f"{k}={v}" for k, v in summary["check_failures"].items()))
    tok = summary["tokens"]
    print(f"  tokens: in {tok['input']} (cache read {tok['cache_read']}), out {tok['output']}"
          f"   est ${summary['est_cost_usd']}")


def _show(args) -> int:
    run_id = args.run_id or latest_run_id()
    if not run_id:
        print("no runs found", file=sys.stderr)
        return 1
    store = RunStore(run_id)
    if not store.manifest_path.exists():
        print(f"run {run_id} has no manifest", file=sys.stderr)
        return 1
    _print_summary(runner.summarize(store))
    return 0


def _rescore(args) -> int:
    personas, scenarios, default, deferrals, problems = loader.load_all()
    if problems:
        print("Layer 0 FAILED - refusing to rescore on bad input:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    run_id = args.run_id or latest_run_id()
    if not run_id:
        print("no runs found", file=sys.stderr)
        return 1
    store = RunStore(run_id)
    print(f"rescoring {run_id} against the current check rules (no API calls)")
    _print_summary(runner.rescore(store, personas, deferrals))
    return 0


def _compare(args) -> int:
    summaries = []
    for run_id in (args.run_a, args.run_b):
        store = RunStore(run_id)
        if not store.manifest_path.exists():
            print(f"run {run_id} has no manifest", file=sys.stderr)
            return 1
        summaries.append(runner.summarize(store))
    diff = runner.compare(*summaries)

    a, b = diff["a"], diff["b"]
    print(f"A  {a['run_id']}  {a['scenario_id']}")
    print(f"B  {b['run_id']}  {b['scenario_id']}\n")
    print("  persona  type                A repeats          B repeats          change")
    for row in diff["rows"]:
        ga = " ".join(MARK[r] for r in row["a"]["results"]) or "-"
        gb = " ".join(MARK[r] for r in row["b"]["results"]) or "-"
        print(f"  {row['persona_id']:<8} {row['persona_type']:<18}  {ga:<18} {gb:<18} {row['change']}")

    for label, s_ in (("A", a), ("B", b)):
        t = s_["totals"]
        total = t["pass"] + t["fail"] + t["no_evidence"]
        rate = (t["pass"] / total * 100) if total else 0.0
        print(f"\n  Layer 2  {label}  pass {t['pass']}/{total} ({rate:.0f}%)   fail {t['fail']}   "
              f"no_evidence {t['no_evidence']}   sut_error {t['sut_error']}   ${s_['est_cost_usd']}")

    # Layer 2 alone has been shown to pass units Layer 3 fails, so never present it as
    # the comparison when judgments exist.
    stores = [RunStore(args.run_a), RunStore(args.run_b)]
    judged = [{j["unit_id"]: j for j in st.iter_judgments()} for st in stores]
    if not all(judged):
        print("\n  (Layer 2 only - run `judge` on both to compare final verdicts)")
        return 0

    print("\n  persona  A final            B final            change")
    for row in diff["rows"]:
        cells = []
        for side, js in zip(("a", "b"), judged):
            verdicts = [js[u]["final"] for u in sorted(js)
                        if js[u]["persona_id"] == row["persona_id"]]
            cells.append((" ".join(MARK[v] for v in verdicts) or "-", verdicts))
        (ga, va), (gb, vb) = cells
        if set(va) == set(vb):
            change = "same"
        elif set(vb) == {"pass"}:
            change = "FIXED"
        elif set(va) == {"pass"}:
            change = "REGRESSED"
        else:
            change = "changed"
        print(f"  {row['persona_id']:<8} {ga:<18} {gb:<18} {change}")

    for label, js in (("A", judged[0]), ("B", judged[1])):
        c = {k: sum(1 for j in js.values() if j["final"] == k)
             for k in ("pass", "fail", "disputed", "no_evidence")}
        total = sum(c.values())
        print(f"\n  final    {label}  pass {c['pass']}/{total} ({c['pass']/total*100:.0f}%)   "
              f"fail {c['fail']}   disputed {c['disputed']}")
    return 0


def _judge(args) -> int:
    personas, scenarios, default, deferrals, problems = loader.load_all()
    shared = rubric.load_rubric(problems)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        problems.append("ANTHROPIC_API_KEY is not set (.env or environment)")
    if problems:
        print("Layer 0 FAILED - refusing to judge:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    run_id = args.run_id or latest_run_id()
    store = RunStore(run_id)
    if not store.manifest_path.exists():
        print(f"run {run_id} has no manifest", file=sys.stderr)
        return 1

    by_id = {p.id: p for p in personas}
    records = [r for r in store.iter_units() if r["status"] == "ok"]
    if args.resume:
        records = [r for r in records if not store.judged(r["unit_id"])]
    tiers = set(args.tiers.split(",")) if args.tiers else None
    roles = C.JUDGE_ROLES[: args.judges]

    manifest = store.read_manifest()
    scenario = scenarios.get(manifest["scenario"]["id"]) or scenarios[default]
    faq = (C.ROOT / scenario.faq_file).read_text(encoding="utf-8")

    # The manifest recorded what produced these transcripts. If an input has
    # changed since, the transcripts predate it - say so rather than silently
    # judging them against a contract they were never given.
    now, then = loader.fingerprints(scenario), manifest.get("inputs", {})
    drifted = [k for k, v in now.items() if k in then and then[k] != v]
    if drifted:
        print(f"  NOTE: these transcripts predate the current {', '.join(drifted)} "
              f"(manifest sha differs). Judging them anyway; re-run the SUT for a clean "
              f"baseline.", file=sys.stderr)

    calls = sum(len(rubric.dimensions_for(by_id[r["persona_id"]], deferrals, shared, tiers))
                for r in records) * len(roles)
    print(f"judging {run_id}: {len(records)} units, {calls} judge calls "
          f"({', '.join(roles)}), concurrency {args.concurrency}")
    if args.dry_run:
        print("dry run - no API calls")
        return 0

    def progress(j: dict) -> None:
        notes = ", ".join(j["failed_dimensions"] + [f"{d} (disputed)" for d in j["disputed_dimensions"]])
        print(f"  L2 {MARK[j['layer2']]}  L3 {MARK[j['layer3']]}  -> {MARK[j['final']]}  "
              f"{j['unit_id']:<34} {notes}", file=sys.stderr, flush=True)

    try:
        asyncio.run(judge.judge_run(
            records, by_id, deferrals, shared, faq,
            roles=roles, concurrency=args.concurrency, tiers=tiers,
            store=store, on_done=progress))
    except FatalRunError as e:
        print(f"\nABORTED - {e}", file=sys.stderr)
        return 2

    _print_judgments(store)
    return 0


def _print_judgments(store) -> int:
    judgments = list(store.iter_judgments())
    if not judgments:
        print("no judgments yet - run: evalkit judge <RUN_ID>", file=sys.stderr)
        return 1

    by_persona: dict[str, list[dict]] = {}
    dim_failures: dict[str, int] = {}
    totals = {"pass": 0, "fail": 0, "disputed": 0, "no_evidence": 0}
    caught_by_l3 = 0
    for j in sorted(judgments, key=lambda j: (j["persona_id"], j["repeat_idx"])):
        by_persona.setdefault(j["persona_id"], []).append(j)
        totals[j["final"]] += 1
        if j["layer2"] != "fail" and j["layer3"] in ("fail", "disputed"):
            caught_by_l3 += 1
        for d in j["failed_dimensions"]:
            dim_failures[d] = dim_failures.get(d, 0) + 1

    print(f"\n  {store.run_id}  {len(judgments)} units judged")
    print(f"  final: pass {totals['pass']}   fail {totals['fail']}   "
          f"disputed {totals['disputed']}   no_evidence {totals['no_evidence']}")
    print("\n  persona  L2 repeats         L3 repeats         final              failed dimensions")
    for pid, js in sorted(by_persona.items()):
        g2 = " ".join(MARK[j["layer2"]] for j in js)
        g3 = " ".join(MARK[j["layer3"]] for j in js)
        gf = " ".join(MARK[j["final"]] for j in js)
        dims = sorted({d for j in js for d in j["failed_dimensions"]})
        dims += sorted({f"{d}?" for j in js for d in j["disputed_dimensions"]})
        print(f"  {pid:<8} {g2:<18} {g3:<18} {gf:<18} {', '.join(dims)}")
    if dim_failures:
        print("\n  dimension failures:",
              ", ".join(f"{k}={v}" for k, v in sorted(dim_failures.items(), key=lambda kv: -kv[1])))
    print(f"  units Layer 2 passed but Layer 3 flagged: {caught_by_l3}")
    return 0


def _golden(args) -> int:
    personas, scenarios, default, deferrals, problems = loader.load_all()
    shared = rubric.load_rubric(problems)
    by_id = {p.id: p for p in personas}
    shared_map = {d.id: d for d in shared}
    cases = goldens.load_cases(by_id, deferrals, shared_map, problems)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        problems.append("ANTHROPIC_API_KEY is not set (.env or environment)")
    if problems:
        print("Layer 0 FAILED - refusing to run the golden set:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",") if c.strip()}
        cases = [c for c in cases if c["id"] in wanted]

    scenario = scenarios[args.scenario or default]
    faq = (C.ROOT / scenario.faq_file).read_text(encoding="utf-8")
    roles = C.JUDGE_ROLES[: args.judges]
    calls = sum(len(c["expect"]) for c in cases) * len(roles)
    print(f"golden set: {len(cases)} cases, {calls} judge calls "
          f"({', '.join(roles)}), concurrency {args.concurrency}")

    try:
        results = asyncio.run(goldens.run(
            cases, by_id, deferrals, shared_map, faq,
            roles=roles, concurrency=args.concurrency))
    except FatalRunError as e:
        print(f"\nABORTED - {e}", file=sys.stderr)
        return 2

    report = goldens.score(results)
    out_dir = C.GOLDENS_DIR / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (out_dir / f"{stamp}.json").write_text(
        json.dumps({"summary": report, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print("\n  case                        dimension                      want  got   ")
    for row in report["rows"]:
        flag = "" if row["ok"] else "   <-- MISS" if row["expected"] == "fail" else "   <-- FALSE POSITIVE"
        if not row["ok"] and row["got"] == "disputed":
            flag = "   (disputed)"
        note = f"  invalid votes: {row['invalid_votes']}" if row["invalid_votes"] else ""
        print(f"  {row['case_id']:<27} {row['dimension_id']:<30} "
              f"{MARK[row['expected']]}  {MARK[row['got']]}{flag}{note}")

    g = report["gate"]
    print(f"\n  recall              {report['recall']:.0%}  "
          f"({report['caught']}/{report['planted_failures']} planted failures confirmed; "
          f"{report['caught_as_disputed']} disputed, {report['missed']} missed)"
          f"   bar {g['min_recall']:.0%}  {'OK' if g['recall_ok'] else 'FAIL'}")
    print(f"  false positive rate {report['false_positive_rate']:.0%}  "
          f"({report['false_positives']}/{report['clean_dimensions']} correct replies condemned; "
          f"{report['false_positives_as_disputed']} disputed)"
          f"   bar {g['max_false_positive_rate']:.0%}  {'OK' if g['false_positive_ok'] else 'FAIL'}")
    if report["abstain_expected"]:
        print(f"  abstentions         {report['abstain_correct']}/{report['abstain_expected']} correct")
    if report["invalid_votes"]:
        print(f"  invalid votes       {report['invalid_votes']} (quote or citation did not check out)")
    tok = report["tokens"]
    print(f"  tokens: in {tok['input']} (cache read {tok['cache_read']}), out {tok['output']}")

    print(f"\n  GATE {'PASSED - judges may score the SUT' if g['passed'] else 'FAILED - fix the rubric before scoring the SUT'}")
    print(f"  saved: {out_dir / (stamp + '.json')}")
    return 0 if g["passed"] else 3


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(prog="evalkit")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("validate", help="Layer 0 only: check inputs, call nothing")

    run_p = sub.add_parser("run", help="Layer 0-2: run units and write transcripts")
    run_p.add_argument("--scenario")
    run_p.add_argument("--personas", help="comma-separated persona ids")
    run_p.add_argument("--repeats", type=int, default=C.DEFAULT_REPEATS)
    run_p.add_argument("--concurrency", type=int, default=C.DEFAULT_CONCURRENCY)
    run_p.add_argument("--resume", metavar="RUN_ID", help="reuse a run dir, skip completed units")
    run_p.add_argument("--dry-run", action="store_true")
    run_p.add_argument("--no-preflight", action="store_true")

    show_p = sub.add_parser("show", help="re-print the summary for a run")
    show_p.add_argument("run_id", nargs="?")

    rescore_p = sub.add_parser("rescore", help="re-apply Layer 2 to stored transcripts, no API calls")
    rescore_p.add_argument("run_id", nargs="?")

    compare_p = sub.add_parser("compare", help="diff two runs per persona")
    compare_p.add_argument("run_a")
    compare_p.add_argument("run_b")

    judge_p = sub.add_parser("judge", help="Layer 3-4: score stored transcripts with LLM judges")
    judge_p.add_argument("run_id", nargs="?")
    judge_p.add_argument("--judges", type=int, default=len(C.JUDGE_ROLES),
                         choices=range(1, len(C.JUDGE_ROLES) + 1))
    judge_p.add_argument("--tiers", help="comma-separated: deferred,persona,safety,quality")
    judge_p.add_argument("--concurrency", type=int, default=C.DEFAULT_JUDGE_CONCURRENCY)
    judge_p.add_argument("--personas", help="unused placeholder for symmetry", default=None)
    judge_p.add_argument("--resume", action="store_true", help="skip units already judged")
    judge_p.add_argument("--dry-run", action="store_true")

    verdicts_p = sub.add_parser("verdicts", help="re-print Layer 3-4 results for a run")
    verdicts_p.add_argument("run_id", nargs="?")

    golden_p = sub.add_parser("golden", help="measure judge recall on planted failures")
    golden_p.add_argument("--scenario", help="which scenario's FAQ to give the judges")
    golden_p.add_argument("--cases", help="comma-separated golden case ids")
    golden_p.add_argument("--judges", type=int, default=len(C.JUDGE_ROLES),
                          choices=range(1, len(C.JUDGE_ROLES) + 1))
    golden_p.add_argument("--concurrency", type=int, default=C.DEFAULT_JUDGE_CONCURRENCY)

    args = parser.parse_args(argv)
    return {"validate": _validate, "run": _run, "show": _show, "rescore": _rescore,
            "compare": _compare, "golden": _golden, "judge": _judge,
            "verdicts": lambda a: _print_judgments(RunStore(a.run_id or latest_run_id()))}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
