# LLM-Guided-Decision-Heuristics-for-SAT-Based-ATPG
LLM-Guided Decision Heuristics for SAT-Based Automatic Test Pattern Generation
- Experimenting whether LLMs can serve as semantic heuristic oracles to guide SAT-based ATPG search and improve solving efficiency

1. Background
   
Automatic Test Pattern Generation (ATPG) is a fundamental problem in digital circuit
testing. Modern ATPG techniques increasingly rely on Boolean Satisfiability (SAT) solvers
to generate test vectors for structural fault models such as stuck-at and transition faults.

In SAT-based ATPG, the test generation problem is encoded as a CNF formula:
- A fault-free circuit model
- A faulty circuit model
- A miter enforcing output divergence
  
A SAT solver is then used to determine whether a test vector exists.
While SAT-based ATPG has shown strong performance improvements over classical
algorithms (e.g., PODEM, FAN), the efficiency of SAT solving heavily depends on internal
heuristics such as:
- Decision variable ordering
- Clause learning
- Branching strategies
These heuristics are purely syntactic and unaware of circuit semantics.


2. Problem Gap

Current SAT-based ATPG approaches:
- Treat each fault independently
- Use generic SAT heuristics (e.g., VSIDS)
- Do not leverage structural or functional circuit knowledge beyond CNF encoding
- Do not learn semantic patterns across faults

  
Large Language Models (LLMs), however, are capable of reasoning over:
- Circuit structure
- Gate-level dependencies
- Sensitization paths
- Functional behavior descriptions
There is currently little to no systematic study on:
Whether LLMs can serve as semantic heuristic oracles to guide SAT-based ATPG search and
improve solving efficiency.

3. Problem Statement

The objective of this project is to design, implement, and evaluate an LLM-guided SAT-
based ATPG framework where the LLM assists the SAT solver by providing structural
decision heuristics for fault activation and propagation.

Specifically, the project must address the following research questions:
1. Can an LLM predict useful partial assignments for fault activation and propagation?
2. Can LLM-guided variable selection reduce SAT solver:
- - Decision count?
- - Conflict count?
- - Solving time?
3. Does LLM guidance improve detection of hard-to-detect faults?
4. Can knowledge transfer across previously solved faults improve performance on new
faults?


4. Proposed Approach
   
Students must implement the following architecture:

Step 1: SAT-Based ATPG Core
- Convert RTL to gate-level netlist (using Yosys or equivalent)
- Encode stuck-at faults in CNF
- Construct good/faulty circuit miter
- Solve using a SAT solver (e.g., MiniSAT / PySAT / Z3)
  
Step 2: LLM Guidance Layer
For each fault instance, the LLM may provide one or more of the following:
- Predicted fault activation conditions
- Suggested sensitization paths
- Partial input assignments
- Variable ordering hints
These hints must be translated into:
- Assumption literals
- Branching priority modifications
- CNF constraints (soft guidance)

Step 3: Closed-Loop Evaluation
If SAT fails or conflicts heavily:
- Extract UNSAT core or conflict information
- Provide structured feedback to LLM
- Refine guidance iteratively

  
5. Expected Novelty

The novelty of this project lies in:
1. Introducing semantic reasoning from LLMs into SAT-based ATPG decision
processes.
2. Formally evaluating LLM impact on solver complexity metrics.
3. Studying hybrid semantic-structural heuristics in ATPG.
4. Investigating cross-fault knowledge reuse via LLM interaction.
This is distinct from classical SAT-ATPG work, which relies solely on algorithmic heuristics
internal to the solver.

6. Experimental Evaluation

Evaluation of framework on benchmark circuits such as:
- ISCAS85 / ISCAS89
- Arithmetic modules (ALU, multipliers)
Metrics to report:
- Fault coverage
- SAT solving time
- Number of decisions
- Conflict count
- Pattern count
- Comparison with baseline SAT-ATPG
Statistical comparison must be included.


7. Deliverables
1. SAT-based ATPG implementation
2. LLM integration module
3. Experimental evaluation report
4. Complexity analysis
5. Discussion on scalability and limitations
Bonus (optional):
- Extension to transition faults
- LLM-guided test point insertion
- Learning across multiple circuits
