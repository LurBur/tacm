# TACM Competitor / Reference Research

## Primary Question

What does TACM do that static LLM routers, cost proxies, and gateway tools do not?

## Working Answer

TACM should not compete as another generic LLM proxy. TACM should compete as an **adaptive control layer** that detects sustained cost-quality divergence, instability, and workload drift before visible quality collapse.

## Reference Repos To Study

| Repo | Category | Why It Matters | TACM Learning Target |
|---|---|---|---|
| NadirRouter/NadirClaw | LLM cost router | Direct open-source cost-router reference with simple/complex task routing and savings-oriented positioning. | Study offer language, routing tiers, proxy architecture, and dashboard framing. |
| tensorzero/tensorzero | LLMOps gateway | Strong reference for gateway, observability, evals, optimization, routing, retries, fallbacks, and experimentation. | Learn production routing + feedback loop architecture. |
| ulab-uiuc/LLMRouter | LLM routing research | Provides many router types including KNN, SVM, MLP, matrix factorization, Elo, graph routing, BERT routing, and hybrid routers. | Use as baseline taxonomy for TACM comparisons. |
| BerriAI/litellm | LLM gateway | Mature provider abstraction layer with spend tracking and routing features. | Use for provider interface and cost tracking patterns. |
| promptfoo/promptfoo | Eval harness | Practical CLI for prompt/model/agent evaluation and CI-style testing. | Use for repeatable TACM evals. |
| RelayPlane/proxy | AI proxy | Local proxy with request tracking, cache-aware cost tracking, routing, provider health, and dashboard patterns. | Compare simple proxy architecture against TACM Lite. |
| vllm-project/semantic-router | Semantic routing | System-level routing approach for mixture-of-models and token economics. | Study high-level adaptive routing framing. |
| infer-actively/pymdp | Active inference | Python active inference implementation. | Map TACM instability/intervention logic to control and inference theory. |
| infer-actively/pypc | Predictive coding | Predictive coding reference. | Support staleness / prediction-error framing. |
| tekacs/llm-pricing | LLM pricing | CLI for provider/model cost calculation. | Add pricing intelligence without manually maintaining every model price. |

## TACM Differentiation Hypothesis

Most routers answer:

> Which model should answer this request?

TACM should answer:

> Which model should answer this request given current confidence, cost pressure, task risk, sustained divergence, workload drift, and phase state?

## Non-Negotiable Benchmark Claim

TACM must beat a fixed-threshold router in at least one measurable condition:

1. Stable workload
2. Drifting workload
3. Shock workload

The likely first winning lane is:

> TACM beats static routing under drifting or shock workloads by preserving quality with lower regret and better intervention timing.

## Revenue Translation

This research supports the paid offer:

> I review your LLM API usage, identify where expensive-model overuse is leaking margin, and provide a routing map. If I cannot find realistic savings, you do not pay.

## First Customer Asset

Create a public-facing benchmark summary:

- Static router baseline
- TACM adaptive router
- Cost saved
- Quality retained
- Failure cases
- What changed under drift

That asset becomes the proof link for cold outreach, Reddit replies, LinkedIn posts, and direct founder messages.
