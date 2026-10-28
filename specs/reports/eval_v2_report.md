# Thread V2 evaluation

Backend: `offline_reference`. Generation: `deterministic_extractive_baseline`.

| Strategy | Recall@k | MRR | Citation precision | Abstention accuracy | Retrieval p95 (ms) |
| --- | --- | --- | --- | --- | --- |
| vector_only | 1.0000 | 1.0000 | 0.9231 | 0.9375 | 0.4088 |
| hybrid | 1.0000 | 1.0000 | 0.9231 | 0.9375 | 0.6265 |

Security violations: 0

## Observed failures

- gdg-q13 / vector_only: unanswerable_answered
- tech-q13 / vector_only: unanswerable_answered
- gdg-q13 / hybrid: unanswerable_answered
- tech-q13 / hybrid: unanswerable_answered

## Limits

- Synthetic corpus; no real-provider inference is measured.
- Offline lexical overlap is not PostgreSQL full-text ranking.
- Prompt-injection checks cover defined boundaries; they are not a universal model robustness guarantee.
