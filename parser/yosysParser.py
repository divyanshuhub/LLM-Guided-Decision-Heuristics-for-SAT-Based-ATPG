# yosysParser.py
# Generic parser: YosysNetlist (Pydantic) -> ParsedNetlist (Pydantic)
#
# Works with:
#   • Yosys internal primitives  ($_AND_, $_OR_, $_NOT_, $_DFF_P_, ...)
#   • Liberty-mapped cells       (AND2_X1, INV_X1, NOR2_X1, ...)
#   • Any unknown cell type      -> GateType.UNKNOWN (never crashes)
#   • Multi-module JSON          -> parse any named module, default = top
#   • Constant tie-offs          -> CONST_0 / CONST_1 signal names

from __future__ import annotations

from typing import Dict, List, Optional

from .yosysModels import (
    BitID,
    Gate,
    GateType,
    ParsedNetlist,
    PortDirection,
    YosysCell,
    YosysModule,
    YosysNetlist,
)


#-------------------------------------------------------------------------
#  Cell-type normalisation table
#
#  Maps every known Yosys cell-type string to GateType enum value.
#-------------------------------------------------------------------------

CELL_TYPE_MAP: Dict[str, GateType] = {
    #----- Yosys internal primitives (before or without tech-mapping)
    "$_AND_":   GateType.AND,
    "$_OR_":    GateType.OR,
    "$_NOT_":   GateType.NOT,
    "$_NAND_":  GateType.NAND,
    "$_NOR_":   GateType.NOR,
    "$_XOR_":   GateType.XOR,
    "$_XNOR_":  GateType.XNOR,
    "$_BUF_":   GateType.BUFF,
    "$_DFF_P_": GateType.DFF,   # positive-edge DFF
    "$_DFF_N_": GateType.DFF,   # negative-edge DFF
    "$_DFFE_PP_": GateType.DFF, # DFF with enable
    "$_DFFE_PN_": GateType.DFF,
    "$_DFFE_NP_": GateType.DFF,
    "$_DFFE_NN_": GateType.DFF,
    "$_ANDNOT_": GateType.ANDNOT,
    "$_ORNOT_":  GateType.ORNOT,
    "$_MUX_":   GateType.UNKNOWN,  # keep as UNKNOWN; extend if needed

    #----- NanGate 45nm Open Cell Library
    "AND2_X1":  GateType.AND,   "AND2_X2":  GateType.AND,
    "AND3_X1":  GateType.AND,   "AND3_X2":  GateType.AND,
    "AND4_X1":  GateType.AND,   "AND4_X2":  GateType.AND,
    "OR2_X1":   GateType.OR,    "OR2_X2":   GateType.OR,
    "OR3_X1":   GateType.OR,    "OR3_X2":   GateType.OR,
    "OR4_X1":   GateType.OR,    "OR4_X2":   GateType.OR,
    "INV_X1":   GateType.NOT,   "INV_X2":   GateType.NOT,
    "INV_X4":   GateType.NOT,   "INV_X8":   GateType.NOT,
    "NAND2_X1": GateType.NAND,  "NAND2_X2": GateType.NAND,
    "NAND3_X1": GateType.NAND,  "NAND3_X2": GateType.NAND,
    "NAND4_X1": GateType.NAND,  "NAND4_X2": GateType.NAND,
    "NOR2_X1":  GateType.NOR,   "NOR2_X2":  GateType.NOR,
    "NOR3_X1":  GateType.NOR,   "NOR3_X2":  GateType.NOR,
    "NOR4_X1":  GateType.NOR,   "NOR4_X2":  GateType.NOR,
    "XOR2_X1":  GateType.XOR,   "XOR2_X2":  GateType.XOR,
    "XNOR2_X1": GateType.XNOR,  "XNOR2_X2": GateType.XNOR,
    "BUF_X1":   GateType.BUFF,  "BUF_X2":   GateType.BUFF,
    "BUF_X4":   GateType.BUFF,  "BUF_X8":   GateType.BUFF,
    "DFFR_X1":  GateType.DFF,   "DFFS_X1":  GateType.DFF,
    "DFF_X1":   GateType.DFF,   "DFF_X2":   GateType.DFF,

    #----- OSU 350nm library
    "AND2":     GateType.AND,   "OR2":      GateType.OR,
    "INVX1":    GateType.NOT,   "INVX2":    GateType.NOT,
    "NAND2":    GateType.NAND,  "NOR2":     GateType.NOR,
    "XOR2":     GateType.XOR,   "XNOR2":    GateType.XNOR,
    "BUFX2":    GateType.BUFF,  "DFF":      GateType.DFF,
}

# Port names that are conventionally outputs when port_directions is absent.
# This is a heuristic fallback for black-box or hand-written cells.
_OUTPUT_PORT_NAMES = frozenset({"Y", "ZN", "Z", "Q", "QN", "CO", "S"})


#-------------------------------------------------------------------------
#  Internal helpers
#-------------------------------------------------------------------------

def _build_net_index(module: YosysModule) -> Dict[int, str]:
    """
    Build a { bit_id: signal_name } lookup table for a module.

    Priority order (highest to lowest):
      1. Primary port names  (user-declared, always clean)
      2. Netnames with hide_name == 0  (user-visible internal names)
      3. Netnames with hide_name == 1  (Yosys auto-generated, last resort)

    This priority ensures clean port names ("a", "y") are never overwritten
    by Yosys-generated names ("$and$design.v$1_Y") for the same bit-ID.
    """
    index: Dict[int, str] = {}

    # Pass 1 — primary ports (highest priority)
    for port_name, port in module.ports.items():
        for bit in port.bits:
            if isinstance(bit, int):
                index[bit] = port_name

    # Pass 2 — visible netnames
    for net_name, net in module.netnames.items():
        if not net.is_hidden:
            for bit in net.bits:
                if isinstance(bit, int) and bit not in index:
                    index[bit] = net_name

    # Pass 3 — hidden netnames (Yosys auto-generated, fill remaining gaps)
    for net_name, net in module.netnames.items():
        if net.is_hidden:
            for bit in net.bits:
                if isinstance(bit, int) and bit not in index:
                    index[bit] = net_name

    return index


def _resolve_bit(bit: BitID, index: Dict[int, str]) -> str:
    """
    Convert a single BitID to a signal name string.

    - Integer -> look up in net index; fallback to "net_<id>" if unmapped
    - "0" / "1" -> "CONST_0" / "CONST_1"  (constant tie-offs)
    """
    if isinstance(bit, int):
        return index.get(bit, f"net_{bit}")
    return f"CONST_{bit}"


def _normalise_gate_type(cell: YosysCell) -> GateType:
    """
    Resolve a YosysCell's type string to a canonical GateType.

    Strategy
    --------
    1. Direct lookup in CELL_TYPE_MAP
    2. Strip Yosys decoration ("$_FOO_" -> "FOO") and match GateType by name
    3. Fall back to GateType.UNKNOWN — never raises, never crashes
    """
    gtype = CELL_TYPE_MAP.get(cell.type)
    if gtype is not None:
        return gtype

    # Strip leading "$_" and trailing "_" then try an enum name match
    stripped = cell.type.strip("$").strip("_").upper()
    # Also handle "AND2_X1" style: take the prefix before the first digit
    prefix = ""
    for ch in stripped:
        if ch.isdigit():
            break
        prefix += ch
    prefix = prefix.rstrip("_")

    for candidate in (stripped, prefix):
        try:
            return GateType(candidate)
        except ValueError:
            pass

    return GateType.UNKNOWN


def _parse_cell(
    cell: YosysCell,
    net_index: Dict[int, str],
) -> Optional[tuple[str, Gate]]:
    """
    Convert one YosysCell into a (output_signal_name, Gate) pair.

    Returns None if no output port can be identified (e.g. a sink cell).
    """
    gtype = _normalise_gate_type(cell)
    output_sig: Optional[str] = None
    input_sigs: List[str]     = []

    for port_name, bits in cell.connections.items():
        if not bits:
            continue
        sig = _resolve_bit(bits[0], net_index)

        # Determine direction: prefer explicit port_directions,
        # fall back to the output-name heuristic
        direction = cell.port_directions.get(port_name)
        if direction is None:
            direction = (
                PortDirection.OUTPUT
                if port_name in _OUTPUT_PORT_NAMES
                else PortDirection.INPUT
            )

        if direction == PortDirection.OUTPUT:
            output_sig = sig
        else:
            input_sigs.append(sig)

    if output_sig is None:
        return None

    return output_sig, Gate(name=output_sig, gtype=gtype, inputs=input_sigs)


#-------------------------------------------------------------------------
#  Public API
#-------------------------------------------------------------------------

def parse_yosys_netlist(
    netlist: YosysNetlist,
    module_name: Optional[str] = None,
) -> ParsedNetlist:
    """
    Convert a validated YosysNetlist into a ParsedNetlist.

    Parameters
    ----------
    netlist     : YosysNetlist
    module_name : which module to parse; defaults to the first module (top)
                  Pass a name explicitly for multi-module JSON files.

    Returns
    -------
    ParsedNetlist with the complete gate graph, PI list, and PO list.

    Algorithm
    ---------
    1. Select the target module
    2. Build bit_id to signal_name index  (ports first, then netnames)
    3. Create INPUT Gate for every primary input port
    4. Parse each cell into a Gate keyed by output signal name
    5. Wrap into ParsedNetlist and return
    """

    #------ 1. Module selection
    if module_name is None:
        mod_name = netlist.top_module_name
        module   = netlist.top_module
    else:
        if module_name not in netlist.modules:
            raise KeyError(
                f"Module '{module_name}' not found. "
                f"Available: {netlist.module_names}"
            )
        mod_name = module_name
        module   = netlist.modules[module_name]

    #------ 2. Net-ID to name index
    net_index = _build_net_index(module)

    #------ 3. Primary input gates
    gates: Dict[str, Gate] = {}
    for pi_name in module.primary_input_names:
        gates[pi_name] = Gate(name=pi_name, gtype=GateType.INPUT, inputs=[])

    #------ 4. Cell to Gate conversion
    for cell_name, cell in module.cells.items():
        result = _parse_cell(cell, net_index)
        if result is None:
            # Cell has no identifiable output — skip (e.g. sink/monitor cells)
            continue
        out_sig, gate = result
        gates[out_sig] = gate

    #----- 5. Wrap and return
    return ParsedNetlist(
        module_name=mod_name,
        gates=gates,
        primary_inputs=module.primary_input_names,
        primary_outputs=module.primary_output_names,
    )


def parse_yosys_file(
    filepath: str,
    module_name: Optional[str] = None,
) -> ParsedNetlist:
    """
    load a Yosys JSON file and parse it.

    Parameters
    ----------
    filepath    : path to the Yosys-generated .json file
    module_name : optional — specify which module to parse (default = top)

    Returns
    -------
    ParsedNetlist object with the complete gate graph, PI list, and PO list.
    """
    netlist = YosysNetlist.from_file(filepath)
    return parse_yosys_netlist(netlist, module_name=module_name)
