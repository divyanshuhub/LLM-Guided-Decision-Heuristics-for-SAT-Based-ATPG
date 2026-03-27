# runBenchmarks.py
# ISCAS85 benchmark library - driven entirely by main.py.
# No argparse, no __main__ block.
#
# Public API:
#   run_suite(...)       - run ATPG on a list of circuits, write CSVs
#   write_circuit_csv()  - write one CSV for a single AtpgResult
#   write_summary_csv()  - write cross-circuit summary CSV
#   load_circuit()       - load a ParsedNetlist by name

from __future__ import annotations

import csv
import os
import statistics
from pathlib import Path
from typing import List, Optional

from parser.benchParser import parse_bench_file, parse_bench_string
from parser.yosysParser import parse_yosys_file
from atpgEngine  import run_atpg, AtpgResult
from circuitViz  import draw_circuit, draw_atpg_run


# -----------------------------------------------------------------------
#  c17 inline definition  (no .bench file required)
# -----------------------------------------------------------------------

C17_BENCH = "\n".join([
    "INPUT(1)", "INPUT(2)", "INPUT(3)", "INPUT(6)", "INPUT(7)",
    "OUTPUT(22)", "OUTPUT(23)",
    "10 = NAND(1, 3)",
    "11 = NAND(3, 6)",
    "16 = NAND(2, 11)",
    "19 = NAND(11, 7)",
    "22 = NAND(10, 16)",
    "23 = NAND(16, 19)",
])


# -----------------------------------------------------------------------
#  ISCAS85 circuit registry  (ordered by gate count)
# -----------------------------------------------------------------------

ISCAS85 = [
    "c17",   "c432",  "c499",  "c880",  "c1355",
    "c1908", "c2670", "c3540", "c5315", "c6288", "c7552",
]


# -----------------------------------------------------------------------
#  Circuit loader
# -----------------------------------------------------------------------

def load_circuit(name: str, bench_dir: str):
    """
    Load a circuit by name.
    Priority : .bench file  >  inline (c17 only)
    Returns a ParsedNetlist, or None if not found.
    """
    bench_file = Path(bench_dir) / (name + ".bench")

    if bench_file.exists():
        print("  Loading bench file  :  " + str(bench_file))
        return parse_bench_file(str(bench_file))

    # if name == "c17":
    #     print("  Loading c17 from inline definition (no file needed)")
    #     return parse_bench_string(C17_BENCH, name="c17")

    print("  Skipping " + name + " - not found in " + bench_dir)
    return None


# -----------------------------------------------------------------------
#  CSV writers
# -----------------------------------------------------------------------

def write_circuit_csv(result: AtpgResult, output_dir: str) -> str:
    """Write one CSV per circuit, one row per fault site."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, result.module_name + "_results.csv")
    rows = result.to_rows()
    if rows:
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    return path


def write_summary_csv(summary_rows: List[dict], output_dir: str) -> str:
    """Write the cross-circuit summary CSV."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "benchmark_summary.csv")
    if summary_rows:
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)
    return path


# -----------------------------------------------------------------------
#  Summary row builder
# -----------------------------------------------------------------------

def _build_summary_row(result: AtpgResult, solver: str) -> dict:
    rows = result.fault_results
    if not rows:
        return {}
    times    = [r.metrics.solver_time_sec for r in rows]
    decs     = [r.metrics.decisions       for r in rows]
    confs    = [r.metrics.conflicts       for r in rows]
    learned  = [r.metrics.learned_clauses for r in rows]
    restarts = [r.metrics.restarts        for r in rows]
    return {
        "circuit":                 result.module_name,
        "total_faults":            result.total_faults,
        "detected_faults":         result.detected_faults,
        "fault_coverage_pct":      round(result.fault_coverage, 2),
        "total_time_seconds":      round(result.total_time_sec, 4),
        "average_solve_ms":        round(statistics.mean(times) * 1000, 4),
        "max_solve_ms":            round(max(times) * 1000, 4),
        "average_decisions":       round(statistics.mean(decs), 2),
        "max_decisions":           max(decs),
        "total_decisions":         sum(decs),
        "average_conflicts":       round(statistics.mean(confs), 2),
        "max_conflicts":           max(confs),
        "total_conflicts":         sum(confs),
        "average_learned_clauses": round(statistics.mean(learned), 2),
        "max_learned_clauses":     max(learned),
        "average_restarts":        round(statistics.mean(restarts), 2),
        "total_restarts":          sum(restarts),
        "solver":                  solver,
    }


# -----------------------------------------------------------------------
#  Full benchmark suite
# -----------------------------------------------------------------------
def run_suite(
    names:         List[str],
    bench_dir:     str,
    output_dir:    str,
    solver:        str,
    extract_proof: bool,
    visualize:     bool,
    verbose:       bool,
) -> List[dict]:
    """
    Run ATPG on every circuit in names.
    Pass names=["all"] to run the full ISCAS85 suite.
    Writes one CSV per circuit and a cross-circuit summary CSV.
    Returns a list of summary row dicts.
    """
    ALL = ["c17", "c432", "c499", "c880", "c1355",
           "c1908", "c2670", "c3540", "c5315", "c6288", "c7552"]

    targets = ALL if (names is None or names == ["all"]) else names

    summary_rows = []

    for name in targets:
        print("\n" + "=" * 68)
        print("  Circuit : " + name.upper())
        print("=" * 68)

        parsed = load_circuit(name, bench_dir)
        if parsed is None:
            continue

        result = run_atpg(
            parsed,
            solver_name   = solver,
            extract_proof = extract_proof,
            verbose       = verbose,
        )

        if visualize:
            draw_atpg_run(parsed, result)

        csv_path = write_circuit_csv(result, output_dir)
        print("\n  Results CSV -> " + csv_path)

        row = _build_summary_row(result, solver)
        if row:
            summary_rows.append(row)

    if summary_rows:
        summary_path = write_summary_csv(summary_rows, output_dir)
        print("\n  Summary CSV -> " + summary_path)

    return summary_rows
# def run_suite(
#     bench_dir:     str,
#     output_dir:    str,
#     solver:        str,
#     extract_proof: bool,
#     visualize:     bool,
#     verbose:       bool,
#     circuits:      Optional[List[str]] = None,
# ) -> List[dict]:
#     """
#     Run ATPG on every circuit in circuits (default = full ISCAS85 suite).
#     Writes one CSV per circuit and a cross-circuit summary CSV.
#     Returns a list of summary row dicts.
#     """
#     targets      = circuits or ISCAS85
#     summary_rows = []


#     for name in targets:
#         print("\n" + "=" * 68)
#         print("  Circuit : " + name.upper())
#         print("=" * 68)

#         parsed = load_circuit(name, bench_dir)
#         if parsed is None:
#             continue

#         result = run_atpg(
#             parsed,
#             solver_name   = solver,
#             extract_proof = extract_proof,
#             verbose       = verbose,
#         )

#         if visualize:
#             draw_atpg_run(parsed, result)

#         csv_path = write_circuit_csv(result, output_dir)
#         print("\n  Results CSV  ->  " + csv_path)

#         row = _build_summary_row(result, solver)
#         if row:
#             summary_rows.append(row)

#     if summary_rows:
#         summary_path = write_summary_csv(summary_rows, output_dir)
#         print("\n  Summary CSV  ->  " + summary_path)

#     return summary_rows
