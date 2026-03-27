# satSolver.py
# PySAT wrapper with full metric extraction.
#
# Two entry points:
#   solve()     — takes a MiterResult directly (primary ATPG path)
#   solve_raw() — takes raw clauses + encoder (general purpose)
#
# Both return a SolveMetrics Pydantic object with every extractable
# metric from PySAT: decisions, conflicts, propagations, restarts,
# learned clauses, DRUP proof lines, UNSAT core, and test vector.
#


from __future__ import annotations

import time
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field

from cnfEncoder import CNFEncoder, CNFFormula
from mitter import MiterResult


# -----------------------------------------------------------------------------
#  Metrics model
# -----------------------------------------------------------------------------

class SolveMetrics(BaseModel):
    """
    Every extractable metric from a PySAT solve call.

    Solver statistics
    -----------------
    satisfiable     : True if SAT, False if UNSAT
    wall_time_sec   : total elapsed time including Python overhead
    solver_time_sec : internal solver timer (microsecond precision, Glucose4)
    restarts        : Luby/geometric restart count
    decisions       : VSIDS branching decisions
    conflicts       : conflict clause triggers (= CDCL backtracks)
    propagations    : BCP unit propagation steps

    Clause metrics
    --------------
    vars_before     : variable count before solve()
    clauses_before  : clause count before solve() — original Tseitin clauses
    vars_after      : variable count after solve()
    clauses_after   : clause count after solve() — includes learned clauses
    learned_clauses : clauses_after - clauses_before (exact CDCL learned count)

    Result fields
    -------------
    test_vector  : PI name → 0/1 assignment (SAT only)
    model        : raw signed-integer model from solver (SAT only)
    drup_proof   : DRUP proof lines — exact learned conflict clauses (UNSAT)
                   Requires Glucose4 (g4) with extract_proof=True
    unsat_core   : assumption literals that caused UNSAT (UNSAT + assumptions)
    assumptions_used : the assumption list passed to this solve call
    fault_signal : the stuck wire (populated when solving a MiterResult)
    fault_value  : 0 or 1 (populated when solving a MiterResult)
    """
    # Result
    satisfiable:      bool             = False
    # Timing
    wall_time_sec:    float            = 0.0
    solver_time_sec:  float            = 0.0
    # Core CDCL stats
    restarts:         int              = 0
    decisions:        int              = 0
    conflicts:        int              = 0
    propagations:     int              = 0
    # Clause counts
    vars_before:      int              = 0
    clauses_before:   int              = 0
    vars_after:       int              = 0
    clauses_after:    int              = 0
    learned_clauses:  int              = 0
    # SAT result
    test_vector:      Dict[str, int]   = Field(default_factory=dict)
    model:            List[int]        = Field(default_factory=list)
    # UNSAT result
    drup_proof:       List[str]        = Field(default_factory=list)
    unsat_core:       List[int]        = Field(default_factory=list)
    # Context
    assumptions_used: List[int]        = Field(default_factory=list)
    fault_signal:     Optional[str]    = None
    fault_value:      Optional[int]    = None

    def to_dict(self) -> dict:
        """
        Flatten to a plain dict for CSV writing.
        Long list fields are truncated to avoid blowing out CSV columns.
        """
        d = self.model_dump()
        d["drup_proof_count"] = len(self.drup_proof)
        d["drup_proof"]       = "|".join(self.drup_proof[:5])
        d["unsat_core"]       = str(self.unsat_core[:10])
        d["model"]            = str(self.model[:10])
        d["test_vector"]      = str(self.test_vector)
        return d


# -----------------------------------------------------------------------------
#  Shared internal solver
# -----------------------------------------------------------------------------

def _run_solver(
    clauses:        List[List[int]],
    var_map:        Dict[str, str],          # prefixed_key → variable int
    primary_inputs: List[str],               # bare PI names (no prefix)
    pi_prefix:      str,                     # prefix used in var_map for PIs
    assumptions:    List[int],
    solver_name:    str,
    extract_proof:  bool,
    fault_signal:   Optional[str],
    fault_value:    Optional[int],
) -> SolveMetrics:
    """
    Internal implementation shared by solve() and solve_raw().
    All public-facing functions normalise their inputs and delegate here.
    """
    try:
        from pysat.formula import CNF as PySATCNF
        from pysat.solvers import Solver
    except ImportError:
        raise ImportError(
            "pysat is required for SAT solving. "
            "Install it with:  pip install python-sat"
        )

    metrics = SolveMetrics(
        assumptions_used = assumptions,
        fault_signal     = fault_signal,
        fault_value      = fault_value,
    )

    formula = PySATCNF(from_clauses=clauses)

    solver_kwargs: dict = {"use_timer": True}
    if extract_proof and solver_name in ("g4", "g3", "lgl"):
        solver_kwargs["with_proof"] = True

    t_wall = time.perf_counter()

    with Solver(name=solver_name, bootstrap_with=formula, **solver_kwargs) as s:

        metrics.vars_before    = s.nof_vars()
        metrics.clauses_before = s.nof_clauses()

        result = s.solve(assumptions=assumptions)
        metrics.satisfiable = bool(result)

        # -- Timing ----------------------------------------------------------
        metrics.wall_time_sec   = time.perf_counter() - t_wall
        metrics.solver_time_sec = s.time()

        # -- Core CDCL statistics ---------------------------------------------
        stats = s.accum_stats()
        metrics.restarts     = stats.get("restarts",     0)
        metrics.decisions    = stats.get("decisions",    0)
        metrics.conflicts    = stats.get("conflicts",    0)
        metrics.propagations = stats.get("propagations", 0)

        # -- Clause counts (learned = delta) ---------------------------------
        metrics.vars_after    = s.nof_vars()
        metrics.clauses_after = s.nof_clauses()
        metrics.learned_clauses = max(
            0, metrics.clauses_after - metrics.clauses_before
        )

        if result:
            # -- SAT: extract test vector from model --------------------------
            model     = s.get_model()
            model_set = set(model)
            metrics.model = model

            for pi in primary_inputs:
                key = f"{pi_prefix}{pi}"
                var = var_map.get(key)
                if var is not None:
                    metrics.test_vector[pi] = 1 if var in model_set else 0

            if extract_proof:
                proof = s.get_proof()
                if proof:
                    metrics.drup_proof = list(proof)

        else:
            # -- UNSAT: extract core and proof --------------------------------
            core = s.get_core()
            if core:
                metrics.unsat_core = list(core)

            if extract_proof:
                proof = s.get_proof()
                if proof:
                    metrics.drup_proof = list(proof)

    return metrics


# -----------------------------------------------------------------------------
#  Public API
# -----------------------------------------------------------------------------

def solve(
    miter:         MiterResult,
    assumptions:   Optional[List[int]] = None,
    solver_name:   str                 = "g4",
    extract_proof: bool                = True,
) -> SolveMetrics:
    """
    Run the SAT solver on a MiterResult (primary ATPG path).

    Parameters
    ----------
    miter         : output of build_miter() — contains formula + both encoders
    assumptions   : optional list of forced literals (signed ints)
                    e.g. [good.get_var("a")] forces PI a=1 in good copy
    solver_name   : PySAT solver id — "g4" (Glucose4, default),
                    "g3" (Glucose3), "cd" (CaDiCaL), "m22" (Minisat)
    extract_proof : if True, collect DRUP proof lines (Glucose4 only)

    Returns
    -------
    SolveMetrics — satisfiable, test_vector, all CDCL statistics
    """
    return _run_solver(
        clauses        = miter.formula.clauses,
        var_map        = miter.good.var_map,
        primary_inputs = miter.formula.var_map and _extract_pis(miter),
        pi_prefix      = "g_",
        assumptions    = assumptions or [],
        solver_name    = solver_name,
        extract_proof  = extract_proof,
        fault_signal   = miter.fault_signal,
        fault_value    = miter.fault_value,
    )


def solve_raw(
    clauses:        List[List[int]],
    encoder:        CNFEncoder,
    primary_inputs: List[str],
    assumptions:    Optional[List[int]] = None,
    solver_name:    str                 = "g4",
    extract_proof:  bool                = True,
) -> SolveMetrics:
    """
    Run the SAT solver on arbitrary clauses + encoder (general purpose path).

    Use this when you have a CNF that isn't a miter — e.g. a pure
    satisfiability check, a custom encoding, or a non-fault query.

    Parameters
    ----------
    clauses        : list of clauses (list of signed int lists)
    encoder        : CNFEncoder whose var_map is used to look up PI variables
    primary_inputs : bare PI signal names (no prefix) to extract test vector
    assumptions    : optional forced literals
    solver_name    : PySAT solver id
    extract_proof  : if True, collect DRUP proof lines

    Returns
    -------
    SolveMetrics — satisfiable, test_vector, all CDCL statistics
    """
    return _run_solver(
        clauses        = clauses,
        var_map        = encoder.var_map,
        primary_inputs = primary_inputs,
        pi_prefix      = encoder.prefix,
        assumptions    = assumptions or [],
        solver_name    = solver_name,
        extract_proof  = extract_proof,
        fault_signal   = None,
        fault_value    = None,
    )


# -----------------------------------------------------------------------------
#  Internal helper
# -----------------------------------------------------------------------------

def _extract_pis(miter: MiterResult) -> List[str]:
    """
    Recover bare PI names from the good encoder's var_map.
    Strips the "g_" prefix from every key that starts with it.
    """
    prefix = miter.good.prefix   # "g_"
    return [
        k[len(prefix):]
        for k in miter.good.var_map
        if k.startswith(prefix)
    ]
