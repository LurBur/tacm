# TACM

Triadic Adaptive Control Module (TACM) is an adaptive routing and control framework focused on cost-aware, quality-preserving decision systems.

## Current Build Target

The first practical product target is **TACM CostRouter**: a lightweight LLM routing layer that decides when to use cheap, mid-tier, or expensive models based on confidence, task risk, cost pressure, quality drift, and sustained instability.

## Core Hypothesis

Static routing rules waste money because they react only to obvious task complexity. TACM should outperform static routing under drifting or unstable workloads by detecting cost-quality divergence earlier and choosing interventions more intelligently.

## MVP Claim To Test

TACM reduces LLM API cost while preserving target quality compared with fixed-threshold routing baselines.

## Initial Repo Structure

```text
README.md
docs/
  COMPETITOR_RESEARCH.md
  TACM_ROUTER_COMPARISON.md
```

## Immediate Priorities

1. Document competitor/reference systems.
2. Define a benchmark comparing TACM against static routing.
3. Build a minimal synthetic prompt benchmark.
4. Convert results into a paid LLM API cost-audit offer.
