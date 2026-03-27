# verifyDeesNuts.py
# Single entry point for SAT-ATPG.
#
# Modes:
#   --verilog FILE.v              Synthesise with Yosys, run full ATPG
#   --bench c17 c432 ...          Run ISCAS85 benchmarks by name (or 'all')
#   --inter                 Prompt for a single fault to test
#
# Examples:
#   python verifyDeesNuts.py --verilog netlists/half_adder.v
#   python verifyDeesNuts.py --verilog netlists/half_adder.v --inter
#   python verifyDeesNuts.py --bench c17
#   python verifyDeesNuts.py --bench c17 --inter
#   python verifyDeesNuts.py --bench c17 c432 c880
#   python verifyDeesNuts.py --bench all

import argparse
import os
import subprocess
import sys

# -----------------------------------------------------------------------------
# Configuration constants — edit these instead of passing CLI flags
# -----------------------------------------------------------------------------

BENCH_DIR     = "./benchmarks"   # directory containing .bench files
OUTPUT_DIR    = "./results"      # CSV output directory
JSONS_DIR     = "./jsons"        # where Yosys JSON files are written

SOLVER        = "g4"             # g4=Glucose4, g3=Glucose3, cd=CaDiCaL, m22=MiniSat
EXTRACT_PROOF = False            # collect DRUP proof lines (slower, g4 only)
VISUALIZE     = True             # print circuit + per-fault terminal output
VERBOSE       = False            # per-fault progress lines inside atpgEngine

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------

from parser            import parse_yosys_file
from atpgEngine        import run_atpg
from circuitViz        import draw_circuit, draw_atpg_run
from runBenchmarks     import run_suite, write_circuit_csv, load_circuit

# -----------------------------------------------------------------------------
# Yosys helper
# -----------------------------------------------------------------------------

def run_yosys(verilog_path: str) -> str:
    """
    Call Yosys to synthesise a Verilog file and emit a JSON netlist.
    Returns the path to the generated JSON file.
    """
    if not os.path.isfile(verilog_path):
        raise FileNotFoundError(f"Verilog file not found: {verilog_path}")

    os.makedirs(JSONS_DIR, exist_ok=True)

    base      = os.path.splitext(os.path.basename(verilog_path))[0]
    json_path = os.path.join(JSONS_DIR, base + ".json")

    yosys_cmd = (
        f"read_verilog {verilog_path}; "
        f"proc; opt; "
        f"write_json {json_path}"
    )

    print(f"  Running Yosys on  : {verilog_path}")
    print(f"  Output JSON       : {json_path}")
    print()

    try:
        result = subprocess.run(
            ["yosys", "-p", yosys_cmd],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Yosys not found. Install with: sudo apt install yosys  "
            "or  brew install yosys"
        )

    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"Yosys synthesis failed for {verilog_path}.")

    print(f"  Yosys JSON successfully generated.\n")
    return json_path


# -----------------------------------------------------------------------------
# Interactive mode
# -----------------------------------------------------------------------------

def mode_interactive(parsed) -> None:
    """
    Print all available fault sites, prompt the user to pick one wire
    and a stuck-at value, then run ATPG for that single fault only.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Build ordered site list: PIs first, then internal wires, then POs
    pi_set  = set(parsed.primary_inputs)
    po_set  = set(parsed.primary_outputs)
    internals = [
        name for name in parsed.gates
        if name not in pi_set
    ]
    all_sites = list(parsed.primary_inputs) + internals

    col = max(len(s) for s in all_sites) + 4

    print()
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Available fault sites")
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()
    print(f"  {'Wire':<{col}}  {'Gate type':<10}  Role")
    print(f"  {'-'*col}  ----------  ----------------")

    for site in all_sites:
        gtype = parsed.gates[site].gtype.value if site in parsed.gates else "INPUT"
        if site in pi_set:
            role = "primary input"
        elif site in po_set:
            role = "primary output"
        else:
            role = "internal wire"
        print(f"  {site:<{col}}  {gtype:<10}  {role}")

    print()

    # Prompt for wire
    while True:
        wire = input("  Enter wire name  : ").strip()
        if wire in parsed.gates or wire in pi_set:
            break
        print(f"  Wire '{wire}' not found. Please choose from the list above.")

    # Prompt for stuck-at value
    while True:
        val = input("  Stuck-at value (0 or 1) : ").strip()
        if val in ("0", "1"):
            stuck_value = int(val)
            break
        print("  Please enter 0 or 1.")

    print()
    print(f"  Running ATPG for  :  {wire} / stuck-at-{stuck_value}")
    print()

    result = run_atpg(
        parsed,
        solver_name   = SOLVER,
        extract_proof = EXTRACT_PROOF,
        verbose       = VERBOSE,
        fault_filter  = [(wire, stuck_value)],
    )

    if VISUALIZE:
        draw_atpg_run(parsed, result)

    csv_path = write_circuit_csv(result, OUTPUT_DIR)
    print(f"\n  Results CSV written to  {csv_path}")


# -----------------------------------------------------------------------------
# Verilog mode
# -----------------------------------------------------------------------------

def mode_verilog(verilog_path: str, interactive: bool = False) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    json_path = run_yosys(verilog_path)
    parsed    = parse_yosys_file(json_path)

    print(f"  Module          : {parsed.module_name}")
    print(f"  Primary inputs  : {parsed.primary_inputs}")
    print(f"  Primary outputs : {parsed.primary_outputs}")
    print(f"  Gate count      : {parsed.gate_count}")
    print()

    if VISUALIZE:
        draw_circuit(parsed)

    if interactive:
        mode_interactive(parsed)
        return

    result = run_atpg(
        parsed,
        solver_name   = SOLVER,
        extract_proof = EXTRACT_PROOF,
        verbose       = VERBOSE,
    )

    if VISUALIZE:
        draw_atpg_run(parsed, result)

    csv_path = write_circuit_csv(result, OUTPUT_DIR)
    print(f"  Results CSV  →  {csv_path}")


# -----------------------------------------------------------------------------
# Benchmark mode
# -----------------------------------------------------------------------------

def mode_bench(circuit_names: list, interactive: bool = False) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(BENCH_DIR,  exist_ok=True)

    if interactive:
        # Interactive only makes sense for one circuit at a time
        name   = circuit_names[0]
        parsed = load_circuit(name, BENCH_DIR)
        if parsed is None:
            print(f"  Could not load circuit: {name}")
            return
        if VISUALIZE:
            draw_circuit(parsed)
        mode_interactive(parsed)
        return

    run_suite(
        names         = None if "all" in circuit_names else circuit_names,
        bench_dir     = BENCH_DIR,
        output_dir    = OUTPUT_DIR,
        solver        = SOLVER,
        extract_proof = EXTRACT_PROOF,
        visualize     = VISUALIZE,
        verbose       = VERBOSE,
    )


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog        = "main.py",
        description = "SAT-ATPG — Automatic Test Pattern Generation via SAT solving",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = """
Examples:
  python main.py --verilog netlists/half_adder.v
  python main.py --verilog netlists/half_adder.v --inter
  python main.py --bench c17
  python main.py --bench c17 --inter
  python main.py --bench c17 c432 c880
  python main.py --bench all
        """,
    )

    p.add_argument(
        "--verilog",
        metavar = "FILE.v",
        help    = "Path to a Verilog source file. Yosys will synthesise it to a "
                  "JSON netlist before ATPG.",
    )
    p.add_argument(
        "--bench",
        metavar = "CIRCUIT",
        nargs   = "+",
        help    = "One or more ISCAS85 circuit names (e.g. c17 c432 c880). "
                  "Use 'all' to run every known ISCAS85 circuit.",
    )
    p.add_argument(
        "--inter",
        action  = "store_true",
        default = False,
        help    = "Prompt for a specific wire and stuck-at value, then run ATPG "
                  "for that single fault only instead of all faults. "
                  "Works with both --verilog and --bench.",
    )
    return p


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    if not args.verilog and not args.bench:
        parser.print_help()
        sys.exit(0)

    if args.verilog:
        mode_verilog(args.verilog, interactive=args.interactive)

    if args.bench:
        mode_bench(args.bench, interactive=args.interactive)


if __name__ == "__main__":
    main()