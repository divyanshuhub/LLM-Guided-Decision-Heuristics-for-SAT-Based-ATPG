# mitter.py
# SAT miter construction for stuck-at fault detection.
#
# A miter encodes two copies of the circuit side by side:
#   Good copy   (prefix "g_") — normal circuit behaviour
#   Faulty copy (prefix "f_") — same circuit with one wire stuck at 0 or 1
#
# Both copies receive the same primary input vector.
# The miter asserts at least one primary output differs between them.
# SAT  → the satisfying assignment IS the test vector that detects the fault.
# UNSAT → the fault is undetectable by any input vector.
#

from __future__ import annotations

from typing import List

from pydantic import BaseModel

from parser.yosysModels import ParsedNetlist
from cnfEncoder import CNFEncoder, CNFFormula


# -----------------------------------------------------------------------------
#  Miter result — what build_miter() returns
# -----------------------------------------------------------------------------

class MiterResult(BaseModel):
    """
    Everything produced by build_miter() in one clean object.

    Fields
    ------
    good    : CNFEncoder for the fault-free circuit copy (prefix "g_")
              Use good.get_var(signal) to find a PI/PO variable after solving.

    faulty  : CNFEncoder for the faulty circuit copy (prefix "f_")
              Use faulty.get_var(signal) to inspect the faulty copy's values.

    formula : CNFFormula holding the complete merged clause set.
              Pass formula.clauses directly to PySAT, or formula.to_dimacs()
              to any DIMACS-compatible solver.

    fault_signal : the wire that was stuck
    fault_value  : 0 (SA0) or 1 (SA1)
    """
    good:         CNFEncoder
    faulty:       CNFEncoder
    formula:      CNFFormula
    fault_signal: str
    fault_value:  int

    model_config = {"arbitrary_types_allowed": True}

    @property
    def primary_inputs(self) -> List[str]:
        """PI signal names — strip the g_ prefix from the good encoder keys."""
        prefix = self.good.prefix  # "g_"
        return [
            k[len(prefix):]
            for k in self.good.var_map
            if k.startswith(prefix)
        ]


# -----------------------------------------------------------------------------
#  Public API
# -----------------------------------------------------------------------------

def build_miter(
    netlist:      ParsedNetlist,
    fault_signal: str,
    fault_value:  int,
) -> MiterResult:
    """
    Build a SAT miter for detecting a single stuck-at fault.

    Parameters
    ----------
    netlist      : parsed circuit (from benchParser or yosysParser)
    fault_signal : name of the wire carrying the stuck-at fault
    fault_value  : 0 for stuck-at-0 (SA0), 1 for stuck-at-1 (SA1)

    Returns
    -------
    MiterResult with good encoder, faulty encoder, and merged CNF formula.

    Miter structure
    ---------------
    Primary inputs -----> Good circuit  (g_*) --> g_outputs ----|
                     │                                          XOR --> OR = 1
                     ---> Faulty circuit (f_*) --> f_outputs ---|
                            |
                          fault injected here

    Variable ranges
    ---------------
    Good copy  : variables 1 .. (good.next_var - 1)
    Faulty copy: variables good.next_var .. (faulty.next_var - 1)
    Miter XORs : variables faulty.next_var .. (next_var - 1)
    """

    # -- Good copy -------------------------------------------------------------
    good = CNFEncoder(prefix="g_", start_var=1)
    good.encode_circuit(netlist)

    # -- Faulty copy (variables continue from where good left off)
    faulty = CNFEncoder(prefix="f_", start_var=good.next_var)

    # Encode every gate EXCEPT the faulted one.
    # Skipping the faulted gate's Tseitin clauses means its
    # backward implications cannot constrain the inputs.
    # The wire is replaced entirely by the unit clause below.
    for gate in netlist.topo_order():
        if gate.name == fault_signal:
            faulty.get_var(gate.name)   # allocate variable only — no clauses
        else:
            faulty.encode_gate(gate)
    

    # -- Inject stuck-at fault into the faulty copy ----------------------------
    faulty.assert_signal(fault_signal, fault_value)

    # -- Merge clause lists ----------------------------------------------------
    all_clauses = list(good.clauses) + list(faulty.clauses)
    all_var_map = {**good.var_map, **faulty.var_map}
    next_var    = faulty.next_var

    # -- Tie primary inputs: g_PI <-> f_PI --------------------------------------
    # Same input vector must drive both copies.
    # g_PI <-> f_PI  encoded as two implications:
    #   (g_PI → f_PI): (-g | f)
    #   (f_PI → g_PI): (-f | g)

    # SKIP the faulted PI — if we tie g_PI = f_PI and also force
    # f_PI = stuck_value, we force g_PI = stuck_value too,
    # making both copies identical.
    is_pi_fault = fault_signal in netlist.primary_inputs
    for pi in netlist.primary_inputs:
        if is_pi_fault and pi == fault_signal: continue     
        g_var = good.var_map[f"g_{pi}"]
        f_var = faulty.var_map[f"f_{pi}"]
        all_clauses.append([ g_var, -f_var])
        all_clauses.append([-g_var,  f_var])

    # -- Miter outputs: assert at least one PO differs -------------------------
    # For each PO pair, create a diff variable = XOR(g_PO, f_PO).
    # Then assert OR(all diff variables) = 1.
    diff_vars = []
    for po in netlist.primary_outputs:
        g_var = good.var_map[f"g_{po}"]
        f_var = faulty.var_map[f"f_{po}"]
        diff  = next_var; next_var += 1
        diff_vars.append(diff)
        # diff <-> (g_PO XOR f_PO)
        all_clauses += [
            [-diff,  g_var,  f_var],
            [-diff, -g_var, -f_var],
            [ diff, -g_var,  f_var],
            [ diff,  g_var, -f_var],
        ]

    # At least one output must differ
    all_clauses.append(diff_vars)

    # -- Build the merged formula ----------------------------------------------
    formula = CNFFormula(
        var_map  = all_var_map,
        clauses  = all_clauses,
        num_vars = next_var - 1,
        prefix   = "miter",
    )

    # Keep good and faulty in sync with the merged state for post-solve lookups
    good.var_map   = all_var_map
    good.clauses   = all_clauses
    good.next_var  = next_var

    faulty.var_map  = all_var_map
    faulty.clauses  = all_clauses
    faulty.next_var = next_var

    return MiterResult(
        good         = good,
        faulty       = faulty,
        formula      = formula,
        fault_signal = fault_signal,
        fault_value  = fault_value,
    )
