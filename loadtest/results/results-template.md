# Load test results

Copy this file to `loadtest/results/<run>.md`, fill in one table per N, and
commit it together with the k6 summary. Never write a number that is not in a
committed results file.

## Environment

| Field | Value |
| --- | --- |
| Date | YYYY-MM-DD |
| Git commit | `<sha>` |
| CPU | |
| RAM | |
| OS | |
| Docker version | |
| k6 version | |
| Stack | `docker compose -f docker-compose.yml -f loadtest/docker-compose.loadtest.yml up -d web` |
| Database | seeded with `seed_demo` |
| `SESSION_MS` | |
| `MSG_INTERVAL_MS` | |
| `MESSAGE_SIZE` | |

## Runs

| N visitors | M agents | Duration | Connect success | p50 connect | p95 connect | p99 connect | p50 visitor→agent | p95 visitor→agent | p99 visitor→agent | p50 agent→visitor | p95 agent→visitor | p99 agent→visitor | Messages sent | Replies sent | 429 | 5xx | WS 1009 | WS 4429 | WS 1003 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 5 | | | | | | | | | | | | | | | | | | |
| 50 | 5 | | | | | | | | | | | | | | | | | | |
| 100 | 5 | | | | | | | | | | | | | | | | | | |
| 200 | 10 | | | | | | | | | | | | | | | | | | |

## Observed degradation point

Describe where latency, error counts or throughput start to break down, and
what the bottleneck looks like (sockets, DB locks, Redis, CPU, a single
Daphne process, ...).
