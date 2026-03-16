

# SAT-Based Automatic Test Pattern Generation (ATPG)

A research-oriented framework for **SAT-based Automatic Test Pattern Generation (ATPG)** for digital circuits.
The system converts **Verilog circuits into CNF formulas**, injects faults, and uses a **SAT solver** to generate **test vectors** that detect faults.

This repository implements the **baseline SAT-ATPG system**, which will later be extended with **LLM-guided decision heuristics** for improved solver performance.

---

# Table of Contents

* Overview
* System Architecture
* ATPG Problem Formulation
* Algorithm
* Repository Structure
* Installation
* Usage
* Benchmarks
* Experimental Evaluation
* Complexity Analysis
* Future Work
* References

---

# Overview

Automatic Test Pattern Generation (ATPG) is a critical process in **digital circuit testing**. Its objective is to automatically generate **input vectors that detect faults** in hardware circuits.

Traditional ATPG methods include:

* D-algorithm
* PODEM
* FAN algorithm

Modern verification systems increasingly rely on **SAT-based ATPG**, which transforms fault detection into a **Boolean satisfiability problem**.

This project implements a **SAT-based ATPG pipeline** capable of:

* parsing synthesized circuits
* generating CNF formulas
* injecting faults
* detecting faults using SAT solving

---

# System Architecture

```
          Verilog RTL
               │
               ▼
           Yosys Synth
               │
               ▼
       Gate-Level Netlist
               │
               ▼
         Netlist Parser
               │
               ▼
          CNF Encoder
               │
               ▼
        Fault Injection
               │
               ▼
         Miter Builder
               │
               ▼
          SAT Solver
               │
               ▼
         Test Vectors
```

---

# ATPG Problem Formulation

Given:

* Circuit **C**
* Fault **f**

We create:

```
Good circuit: C
Faulty circuit: Cf
```

A **miter circuit** is constructed such that:

```
M = OR (Ci_output XOR Cfi_output)
```

Fault detection becomes the SAT problem:

```
Find input vector x such that:

C(x) ≠ Cf(x)
```

If the SAT solver returns a satisfying assignment:

```
SAT → fault detectable
```

If UNSAT:

```
UNSAT → fault redundant
```

---

# SAT Encoding

Each logic gate is converted into **CNF clauses** using Tseitin encoding.

Example:

### AND Gate

```
Z = A ∧ B
```

CNF clauses:

```
(¬A ∨ ¬B ∨ Z)
(A ∨ ¬Z)
(B ∨ ¬Z)
```

### OR Gate

```
Z = A ∨ B
```

CNF:

```
(A ∨ B ∨ ¬Z)
(¬A ∨ Z)
(¬B ∨ Z)
```

### XOR Gate

```
Z = A ⊕ B
```

CNF:

```
(A ∨ B ∨ ¬Z)
(¬A ∨ ¬B ∨ ¬Z)
(A ∨ ¬B ∨ Z)
(¬A ∨ B ∨ Z)
```

---

# Algorithm

### SAT-Based ATPG

```
Algorithm SAT_ATPG(Circuit C)

1  Parse gate-level netlist
2  Extract wires and gates
3  Generate fault list

4  for each fault f in faults:

5      Construct faulty circuit Cf
6      Duplicate circuit → (C , Cf)

7      Build miter:
           M = XOR(C.output , Cf.output)

8      Convert circuit to CNF

9      Add clause:
           M = 1

10     result ← SAT_SOLVE(CNF)

11     if result == SAT:
12         extract input assignment
13         record test vector

14     else:
15         mark fault undetectable

16 return test_vectors
```

---

# Repository Structure

```
sat_atpg_project/

├── circuits/
│   ├── and.v
│   ├── adder.v
│
├── netlists/
│   └── netlist.json
│
├── netlist_parser.py
├── cnf_encoder.py
├── fault_manager.py
├── miter_builder.py
├── sat_engine.py
│
├── main.py
│
└── README.md
```

---

# Module Description

### netlist_parser.py

Parses Yosys JSON netlist and extracts:

* gate types
* wire connections

---

### cnf_encoder.py

Converts gates to CNF clauses.

Supported gates:

* AND
* OR
* NOT
* XOR

---

### fault_manager.py

Generates faults using the **stuck-at fault model**.

Fault types:

```
wire stuck-at-0
wire stuck-at-1
```

---

### miter_builder.py

Constructs the **miter circuit** comparing good and faulty circuits.

---

### sat_engine.py

Runs SAT solving using **PySAT**.

Responsibilities:

* clause management
* solver execution
* model extraction

---

### main.py

Entry point of the ATPG pipeline.

---

# Installation

## Requirements

* Python ≥ 3.8
* Yosys
* PySAT

---

### Install Yosys

```
sudo apt install yosys
```

---

### Install Python dependencies

```
pip install python-sat[pblib,aiger]
```

---

# Generating Netlist

Example circuit:

```
module and_gate(input A, input B, output Y);
assign Y = A & B;
endmodule
```

Run synthesis:

```
yosys
```

```
read_verilog circuits/and.v
synth
write_json netlists/netlist.json
```

---

# Running the ATPG Engine

```
python main.py
```

Example output:

```
Testing fault: wire 3 stuck-at-0
Test vector found: A=1 B=1

Testing fault: wire 3 stuck-at-1
Fault not detectable
```

---

# Benchmarks

Recommended benchmark circuits:

### ISCAS85

Common combinational circuits:

```
c432
c499
c880
c1355
c1908
```

### ISCAS89

Sequential benchmark circuits.

---

# Experimental Evaluation

Metrics to evaluate ATPG performance:

| Metric         | Description                |
| -------------- | -------------------------- |
| Fault Coverage | % of detectable faults     |
| SAT Solve Time | Time to solve each fault   |
| Decision Count | Number of solver decisions |
| Conflict Count | SAT conflicts              |
| Pattern Count  | Generated test vectors     |

---

# Complexity Analysis

Let:

```
n = number of gates
f = number of faults
```

CNF size:

```
O(n)
```

SAT solving complexity:

```
Worst case: exponential
Typical case: near polynomial with modern heuristics
```

Total ATPG complexity:

```
O(f * SAT(n))
```

---

# Future Work

This system will be extended to implement:

## LLM-Guided SAT Heuristics

The LLM may provide:

* fault activation hints
* propagation path suggestions
* variable branching priorities
* partial input assignments

Expected benefits:

* reduced SAT search space
* fewer conflicts
* faster test vector generation

---

# Research Motivation

Traditional SAT solvers rely on **syntactic heuristics** (VSIDS, clause learning).

This research explores whether **semantic reasoning from Large Language Models** can guide SAT solving using circuit knowledge.

---

# References

1. SAT-Based ATPG Literature
2. ISCAS Benchmark Circuits
3. PySAT Documentation
4. Yosys Open Synthesis Suite

---

# License

MIT License

---

If you want, I can also give you **three extra things that will dramatically improve this repo for research submission**:

1. **A circuit visualization tool (Netlist → graph)**
2. **Automatic benchmark runner (ISCAS experiments)**
3. **A results table generator for your research paper**

These three things make the project look **like a proper MS research repository.**
