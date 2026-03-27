# circuitViz.py
# Terminal circuit visualizer for SAT-ATPG.

from __future__ import annotations
import re
from typing import Dict, List

from parser.yosysModels import Gate, GateType, ParsedNetlist
from atpgEngine import AtpgResult, FaultResult

# -- ANSI colour codes ---------------------------------------------------------
RESET      = "\033[0m"
BOLD       = "\033[1m"
FAINT      = "\033[2m"
RED        = "\033[91m"
GREEN      = "\033[92m"
YELLOW     = "\033[93m"
CYAN       = "\033[96m"
WHITE      = "\033[97m"
BG_RED     = "\033[41m"

SEPARATOR  = f"\n  {'═' * 100}\n"   # thick line between each fault block
DIVIDER    = f"  {'-' * 100}"        # thin line under column headers


# -- Gate evaluator ------------------------------------------------------------

def _eval_gate(gate_type, input_values):
    try:
        a = input_values[0]
        b = input_values[1] if len(input_values) > 1 else None
        if gate_type == "AND":  return int(all(input_values))
        if gate_type == "OR":   return int(any(input_values))
        if gate_type == "NAND": return int(not all(input_values))
        if gate_type == "NOR":  return int(not any(input_values))
        if gate_type == "NOT":  return int(not a)
        if gate_type == "XOR":  return int(a ^ b)
        if gate_type == "XNOR": return int(not (a ^ b))
        if gate_type == "BUFF": return int(a)
    except Exception:
        pass
    return "?"


def _levelize(netlist):
    """Assign logic depth (0 = primary input) to every signal via BFS."""
    depth = {pi: 0 for pi in netlist.primary_inputs}
    changed = True
    while changed:
        changed = False
        for name, gate in netlist.gates.items():
            if not gate.inputs:
                continue
            if all(inp in depth for inp in gate.inputs):
                new_depth = max(depth[inp] for inp in gate.inputs) + 1
                if depth.get(name) != new_depth:
                    depth[name] = new_depth
                    changed = True
    return depth


def _visible_len(text):
    """Return the printable length of a string, stripping ANSI escape codes."""
    return len(re.sub(r'\033\[[0-9;]*m', '', text))


# -----------------------------------------------------------------------------
#  draw_circuit — print bare gate table with no fault annotation
# -----------------------------------------------------------------------------

def draw_circuit(netlist: ParsedNetlist) -> None:
    depth  = _levelize(netlist)
    non_pi = sorted(
        [gate for gate in netlist.gates.values() if not gate.is_primary_input],
        key=lambda gate: (depth.get(gate.name, 0), gate.name),
    )

    print(SEPARATOR)
    print(f"  {BOLD}{WHITE}CIRCUIT : {netlist.module_name.upper()}{RESET}"
          f"  {FAINT}({len(non_pi)} gates,"
          f" {len(netlist.primary_inputs)} primary inputs,"
          f" {len(netlist.primary_outputs)} primary outputs){RESET}")
    print()
    print(f"  {FAINT}Primary inputs  : {', '.join(netlist.primary_inputs)}{RESET}")
    print(f"  {FAINT}Primary outputs : {', '.join(netlist.primary_outputs)}{RESET}")
    print()
    print(f"  {FAINT}{'Input wires':<32}  {'Gate type':<12}  Output wire{RESET}")
    print(DIVIDER)

    for gate in non_pi:
        input_labels = ", ".join(f"{CYAN}{wire}{RESET}" for wire in gate.inputs)
        is_primary_output = gate.name in netlist.primary_outputs
        output_label = (f"{BOLD}{GREEN}{gate.name}{RESET}"
                        if is_primary_output else f"{YELLOW}{gate.name}{RESET}")
        padding = max(0, 32 - _visible_len(input_labels))
        print(f"  {input_labels}{' ' * padding}  [{gate.gtype.value}]  →  {output_label}")

    print(SEPARATOR)


# -----------------------------------------------------------------------------
#  draw_fault — print circuit annotated with stuck-at fault + test vector
# -----------------------------------------------------------------------------

def draw_fault(netlist: ParsedNetlist, fr: FaultResult,
               index: int = 0, total: int = 0) -> None:

    stuck_signal  = fr.fault_signal
    stuck_value   = fr.fault_value
    test_vector   = fr.metrics.test_vector
    is_satisfiable = fr.metrics.satisfiable
    metrics       = fr.metrics

    # -- Fault header ----------------------------------------------------------
    print(SEPARATOR)

    counter = f"{FAINT}[Fault {index} of {total}]{RESET}  " if total else ""
    print(f"  {counter}{BOLD}Fault site : {RED}{fr.fault_label}{RESET}"
          f"   →   wire {CYAN}{stuck_signal}{RESET} is "
          f"{BOLD}{RED}permanently stuck at {stuck_value}{RESET}")

    if is_satisfiable:
        vector_parts = "   ".join(
            f"{CYAN}{signal}{RESET} = {YELLOW}{value}{RESET}"
            for signal, value in test_vector.items()
        )
        print(f"  Test vector that detects this fault  ▶   {vector_parts}")
    else:
        print(f"  {FAINT}No test vector exists — this fault cannot be detected by any input combination{RESET}")

    # -- Gate-by-gate table ----------------------------------------------------
    print()
    print(f"  {FAINT}{'Input':<40}  {'Gate':<16}  "
          f"{'Output':<18}  {'Good':>14}  "
          f"{'Faulty':>14}{RESET}")
    print(DIVIDER)

    depth  = _levelize(netlist)
    non_pi = sorted(
        [gate for gate in netlist.gates.values() if not gate.is_primary_input],
        key=lambda gate: (depth.get(gate.name, 0), gate.name),
    )

    for gate in non_pi:
        this_gate_is_stuck = (gate.name == stuck_signal)

        # Build input wire labels with values
        input_labels = []
        for wire in gate.inputs:
            if wire == stuck_signal:
                input_labels.append(
                    f"{BG_RED}{BOLD}{wire} = {stuck_value} (stuck){RESET}"
                )
            elif is_satisfiable:
                value = test_vector.get(wire, "?")
                input_labels.append(f"{CYAN}{wire}{RESET} = {YELLOW}{value}{RESET}")
            else:
                input_labels.append(f"{FAINT}{wire} = unknown{RESET}")

        inputs_str  = ",  ".join(input_labels)

        # Gate type label — highlighted if this is the stuck gate
        gate_label = f"[{gate.gtype.value}]"
        if this_gate_is_stuck:
            gate_str = f"{BG_RED}{BOLD}{gate_label}{RESET}"
        else:
            gate_str = gate_label

        # Output wire label
        if this_gate_is_stuck:
            output_str = f"{BG_RED}{BOLD}{gate.name}  (stuck at {stuck_value}){RESET}"
        elif gate.name in netlist.primary_outputs:
            output_str = f"{BOLD}{GREEN}{gate.name}{RESET}"
        else:
            output_str = f"{YELLOW}{gate.name}{RESET}"

        # Compute good and faulty output values
        good_output_value   = "unknown"
        faulty_output_value = "unknown"

        if is_satisfiable:
            normal_inputs = {wire: test_vector.get(wire, 0) for wire in gate.inputs}
            good_output_value = _eval_gate(gate.gtype.value, list(normal_inputs.values()))

            if this_gate_is_stuck:
                faulty_output_value = stuck_value
            else:
                faulty_inputs = {
                    wire: (stuck_value if wire == stuck_signal else normal_inputs[wire])
                    for wire in gate.inputs
                }
                faulty_output_value = _eval_gate(
                    gate.gtype.value, list(faulty_inputs.values())
                )

        outputs_differ = is_satisfiable and (good_output_value != faulty_output_value)
        difference_label = (f"  {BOLD}{GREEN}← output mismatch{RESET}"
                            if outputs_differ else "")

        # Padding to align columns
        inputs_pad  = max(0, 40 - _visible_len(inputs_str))
        gate_pad    = max(0, 16 - _visible_len(gate_str))
        output_pad  = max(0, 18 - _visible_len(output_str))

        print(f"  {inputs_str}{' ' * inputs_pad}  "
              f"{gate_str}{' ' * gate_pad}  "
              f"{output_str}{' ' * output_pad}  "
              f"{str(good_output_value):>14}  "
              f"{str(faulty_output_value):>14}"
              f"{difference_label}")

    # -- Result line -----------------------------------------------------------
    print()
    if is_satisfiable:
        result_text = f"{BOLD}{GREEN}✓  FAULT DETECTED{RESET}"
    else:
        result_text = f"{BOLD}{RED}✗  FAULT NOT DETECTABLE{RESET}"

    print(f"  {result_text}"
          f"   {FAINT}"
          f"decisions = {metrics.decisions}   "
          f"conflicts = {metrics.conflicts}   "
          f"propagations = {metrics.propagations}   "
          f"solver time = {metrics.solver_time_sec * 1000:.2f} ms"
          f"{RESET}")


# -----------------------------------------------------------------------------
#  draw_atpg_run — draw circuit once then every fault block
# -----------------------------------------------------------------------------

def draw_atpg_run(netlist: ParsedNetlist, result: AtpgResult) -> None:
    draw_circuit(netlist)
    total = len(result.fault_results)
    for index, fault_result in enumerate(result.fault_results, 1):
        draw_fault(netlist, fault_result, index=index, total=total)

    coverage        = result.fault_coverage
    coverage_color  = GREEN if coverage == 100.0 else YELLOW

    print(SEPARATOR)
    print(f"  {BOLD}{WHITE}ATPG COMPLETE  —  {result.module_name.upper()}{RESET}")
    print()
    print(f"  Fault coverage       :  "
          f"{coverage_color}{BOLD}{result.detected_faults} of {result.total_faults}"
          f" faults detected  ({coverage:.1f}%){RESET}")
    print(f"  Detected             :  {GREEN}{result.detected_faults}{RESET}")
    print(f"  Not detectable       :  {RED}{result.total_faults - result.detected_faults}{RESET}")
    print(f"  Total wall time      :  {result.total_time_sec:.4f} seconds")
    print(SEPARATOR)
