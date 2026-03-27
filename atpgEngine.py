# atpgEngine.py
# SAT-based ATPG engine.
# Delegates all solving and metric extraction to satSolver.solve().
# Collects results into AtpgResult.

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from parser.yosysModels import ParsedNetlist
from mitter             import build_miter, MiterResult
from satSolver          import solve, SolveMetrics

# -----------------------------------------------------------------------------
# Result models
# -----------------------------------------------------------------------------

class FaultResult(BaseModel):
    fault_signal: str
    fault_value:  int
    metrics:      SolveMetrics = Field(default_factory=SolveMetrics)

    model_config = {"arbitrary_types_allowed": True}

    @property
    def label(self) -> str:
        return f"{self.fault_signal}/SA{self.fault_value}"

    # circuitViz.py uses fr.fault_label — keep both as aliases
    @property
    def fault_label(self) -> str:
        return self.label

    @property
    def detected(self) -> bool:
        return self.metrics.satisfiable

    @property
    def test_vector(self) -> Dict[str, int]:
        return self.metrics.test_vector

    def to_row(self) -> dict:
        return {
            "fault":              self.label,
            "signal":             self.fault_signal,
            "stuck_at":           self.fault_value,
            "detected":           self.detected,
            "test_vector":        str(self.test_vector) if self.test_vector else "",
            "decisions":          self.metrics.decisions,
            "conflicts":          self.metrics.conflicts,
            "propagations":       self.metrics.propagations,
            "restarts":           self.metrics.restarts,
            "learned_clauses":    self.metrics.learned_clauses,
            "solver_time_ms":     round(self.metrics.solver_time_sec * 1000, 4),
            "wall_time_ms":       round(self.metrics.wall_time_sec   * 1000, 4),
            "vars_before":        self.metrics.vars_before,
            "clauses_before":     self.metrics.clauses_before,
        }


class AtpgResult(BaseModel):
    module_name:    str
    fault_results:  List[FaultResult] = Field(default_factory=list)
    total_time_sec: float             = 0.0

    @property
    def total_faults(self) -> int:
        return len(self.fault_results)

    @property
    def detected_faults(self) -> int:
        return sum(1 for r in self.fault_results if r.detected)

    @property
    def fault_coverage(self) -> float:
        if self.total_faults == 0:
            return 0.0
        return self.detected_faults / self.total_faults * 100.0

    def print_summary(self) -> None:
        print(f"  Circuit           : {self.module_name}")
        print(f"  Total faults      : {self.total_faults}")
        print(f"  Detected          : {self.detected_faults}")
        print(f"  Not detectable    : {self.total_faults - self.detected_faults}")
        print(f"  Fault coverage    : {self.fault_coverage:.2f}%")
        print(f"  Total wall time   : {self.total_time_sec:.4f}s")

    def to_rows(self) -> List[dict]:
        return [r.to_row() for r in self.fault_results]


# -----------------------------------------------------------------------------
# Signals to skip as fault sites (power/ground constants)
# -----------------------------------------------------------------------------

_SKIP_SIGNALS = frozenset({"0", "1", "CONST_0", "CONST_1"})


# -----------------------------------------------------------------------------
# Core ATPG engine
# -----------------------------------------------------------------------------

def run_atpg(
    netlist:       ParsedNetlist,
    solver_name:   str                             = "g4",
    extract_proof: bool                            = False,
    verbose:       bool                            = False,
    fault_filter:  Optional[List[Tuple[str, int]]] = None,
) -> AtpgResult:
    """
    Run stuck-at ATPG on every fault site in the netlist.

    Parameters
    ----------
    netlist       : parsed circuit
    solver_name   : PySAT solver key  (g4, g3, cd, m22)
    extract_proof : collect DRUP proof lines for UNSAT results (g4 only)
    verbose       : print one progress line per fault while solving
    fault_filter  : if given, only solve the listed (signal, value) pairs
                    e.g.  [("N11", 0)]  runs only N11/SA0
    """
    # Build full fault list — SA0 and SA1 for every gate output
    all_faults: List[Tuple[str, int]] = [
        (name, fv)
        for name in netlist.gates
        if name not in _SKIP_SIGNALS
        for fv in [0, 1]
    ]

    # Narrow to requested faults if a filter was provided
    if fault_filter is not None:
        filter_set = set(fault_filter)
        all_faults = [(n, v) for (n, v) in all_faults if (n, v) in filter_set]

    total   = len(all_faults)
    results = AtpgResult(module_name=netlist.module_name)

    print(
        f"\n  [{netlist.module_name}]  "
        f"{netlist.gate_count} gates  "
        f"{len(netlist.primary_inputs)} primary inputs  "
        f"{len(netlist.primary_outputs)} primary outputs  "
        f"{total} fault sites\n"
    )

    suite_start = time.perf_counter()

    for idx, (signal, fval) in enumerate(all_faults, start=1):

        # Build miter and solve — satSolver.solve() returns a SolveMetrics
        miter: MiterResult   = build_miter(netlist, signal, fval)
        metrics: SolveMetrics = solve(
            miter         = miter,
            solver_name   = solver_name,
            extract_proof = extract_proof,
        )

        fr = FaultResult(
            fault_signal = signal,
            fault_value  = fval,
            metrics      = metrics,
        )
        results.fault_results.append(fr)

        if verbose:
            status = "DETECTED      " if metrics.satisfiable else "NOT DETECTABLE"
            print(
                f"  [{idx:>4}/{total}]  {fr.label:<24}  {status}  "
                f"decisions = {metrics.decisions:>6}  "
                f"conflicts = {metrics.conflicts:>6}  "
                f"solver time = {metrics.solver_time_sec * 1000:>7.2f} ms"
            )

    results.total_time_sec = time.perf_counter() - suite_start
    return results