# TACM Router Comparison Matrix

## Purpose

This document exists to keep TACM grounded against real routing systems instead of becoming a private mythology with Python files attached.

## Comparison Matrix

| System | Routing Method | Cost Tracking | Quality Eval | Fallback Logic | Dashboard | Adaptive Feedback | Instability Detection | Where TACM Must Differ |
|---|---|---:|---:|---:|---:|---:|---:|---|
| Static Threshold Router | Rule-based confidence/complexity thresholds | Minimal | Minimal | Basic | No | No | No | TACM must adapt phase behavior instead of using fixed thresholds. |
| NadirClaw | Simple/complex task classification + routing | Yes | Limited/unknown | Yes | Yes | Limited/unknown | Not primary claim | TACM must focus on sustained divergence and drift response. |
| TensorZero | Gateway + observability + evals + experimentation | Yes | Yes | Yes | Yes | Yes | Indirect | TACM must provide a distinct control policy, not just infra. |
| LLMRouter | Multiple learned routing strategies | Depends on implementation | Research-oriented | Varies | No | Model-dependent | No | TACM must compare against these router classes in benchmark form. |
| LiteLLM | Provider gateway + spend tracking + routing options | Yes | Limited by setup | Yes | Yes | Limited | No | TACM can potentially sit above LiteLLM as decision/control layer. |
| Promptfoo | Evaluation framework, not router | No | Yes | No | Reports | Eval loop only | No | TACM can use Promptfoo for test harness and regression evals. |
| RelayPlane | Proxy with routing, tracking, circuit breaker | Yes | Limited/unknown | Yes | Yes | Some provider health logic | Limited | TACM must outperform simple health/cost routing under drift. |
| vLLM Semantic Router | Semantic/system routing | Token economics oriented | Varies | Varies | Not primary | Yes | Indirect | TACM must define phase-level adaptive intervention. |
| pymdp / pypc | Active inference / predictive coding | No | No | No | No | Theoretical | Prediction-error oriented | TACM can borrow language for instability and control timing. |

## TACM Target Position

TACM should be positioned as:

> An adaptive control layer for LLM routing that uses cost, confidence, quality, risk, and sustained divergence to decide when to stabilize, explore, or escalate.

## First Benchmark Design

### Baselines

1. Static threshold router
2. Random router
3. Simple complexity classifier router
4. TACM adaptive router

### Environments

1. Stable workload
2. Drifting workload
3. Shock workload

### Prompt Classes

1. Simple transformation
2. Medium reasoning
3. High-risk reasoning

### Metrics

| Metric | Meaning |
|---|---|
| Total cost | Aggregate simulated or real API spend |
| Average quality | Score from heuristic, LLM judge, or task-specific evaluator |
| Regret | Penalty for choosing a model that was too cheap or too expensive |
| Fallback rate | How often router escalates after weak answer |
| Phase switches | How often TACM changes mode |
| Drift response time | How fast TACM reacts to workload change |
| Stability score | How consistently it preserves quality over time |

## MVP Pass Condition

TACM does not need to beat everything everywhere.

It needs one strong, honest claim:

> Under drifting workloads, TACM preserves target quality with lower cost than fixed-threshold routing.

## Kill Criteria

Kill or redesign the router if:

1. TACM only matches a simple threshold router.
2. TACM saves cost only by destroying quality.
3. TACM requires so much complexity that nobody can explain it in one sentence.
4. TACM cannot produce a clear chart showing cost vs quality improvement.

## Continue Criteria

Continue if TACM shows:

1. Lower cost at equal quality.
2. Equal cost with higher stability.
3. Better response under drift/shock.
4. Better fallback timing than fixed thresholds.

## Sales Translation

A prospect does not care about phase theory.

A prospect cares about this:

> Your app may be sending too many easy tasks to expensive models. I can audit that and show a lower-cost routing plan.

TACM becomes credible only after the benchmark turns into proof.
