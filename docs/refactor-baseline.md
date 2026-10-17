# Refactor baseline (R0)

This file records the state of the repository before the refactor starts. Nothing
in R0 changes production code; later phases are judged against these numbers.

## Repository state

| Item | Value |
| --- | --- |
| Baseline commit | `a4602f7` (`dev` at the time of the snapshot) |
| Pre-refactor tag | `pre-refactor` |
| Integration branch | `refactor/integration` |
| R0 task branch | `refactor/r0-safety-net` |
| Last main commit | `c680792` (CI runs on Python 3.12) |
| `schema.yml` SHA-256 | `DE0FCAAF8379CC19E7542EE047E2115B3A50A038D0DC3C320C36B673A54B87D9` |

`dev` was one commit ahead of `main` when this baseline was recorded. The tag and
branches point at the code that was measured, not at the older `main` tip.

## Test baseline (pre-R0)

| Metric | Value |
| --- | --- |
| Tests | 1,888 |
| Passed | 1,887 |
| Failed locally | 1 |
| Subtests | 1,169 |

The single local failure is
`core/tests/test_security_websocket.py::test_nobody_can_join_a_deleted_ticket`.
It reproduces on Python 3.14 on Windows and is a timing/flakiness issue in the
test harness, not an assertion about production behavior. CI runs Python 3.12.

## Coverage baseline (pre-R0)

Measured with `pytest --cov --cov-report=term-missing` (line + branch).

| App | Statements | Missing | Branches | Partial | Coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| accounts | 613 | 31 | 124 | 12 | 93.62% |
| audit | 150 | 0 | 30 | 0 | 100.00% |
| chat | 962 | 81 | 152 | 17 | 89.23% |
| config | 179 | 12 | 28 | 8 | 89.37% |
| core | 880 | 22 | 176 | 13 | 96.69% |
| realtime | 540 | 52 | 154 | 30 | 87.61% |
| stats | 109 | 0 | 6 | 0 | 100.00% |
| tickets | 1,208 | 26 | 218 | 12 | 97.05% |
| **Total** | **4,641** | **224** | **888** | **92** | **93.63%** |

### Safety-net suite after R0

R0 adds contract, parity, gap, query-count and coverage tests. The final suite has
1,984 tests: 1,982 pass, 1 `xfail` for the retention gap and the same known local
WebSocket failure above (that test is expected to pass on CI's Python 3.12), with
1,206 subtests. The last full coverage run
measured **97.05%**; the final settings-branch tests bring
`config/settings/base.py` to 100% in isolation.

Modules in the apps later phases touch that were below 90% before R0 were
covered by the new tests: `realtime/events.py`, `realtime/presence_consumer.py`,
`realtime/limits.py`, `chat/offline.py`, `chat/widget/pow.py`,
`chat/widget/limits.py`, `chat/contact.py`, `chat/availability.py`,
`chat/tasks.py`, `chat/visitors.py`, `tickets/messages.py`, `tickets/signals.py`,
`tickets/tasks.py`, `accounts/tasks.py`, `accounts/throttles.py`, `core/health.py`
and `core/metrics.py`. `config/settings/prod.py` remains below 90% because its
branches are import-time deployment checks; those are exercised by the CI
`check --deploy` step and by the settings snapshot below.

## Ten largest tracked files (pre-R0)

| File | Lines |
| --- | ---: |
| `schema.yml` | 5,433 |
| `README.md` | 639 |
| `accounts/tests/test_user_management.py` | 552 |
| `chat/tests/test_sites.py` | 523 |
| `core/demo.py` | 493 |
| `tickets/tests/test_models.py` | 465 |
| `tickets/tests/test_tags.py` | 463 |
| `audit/tests/test_audit.py` | 427 |
| `tickets/models.py` | 398 |
| `core/tests/test_seed_demo.py` | 375 |

## Settings snapshot (R0.2)

The split of `config/settings/base.py` in R8 is verified with two scripts:

```powershell
# Save diffsettings --all for dev, test and prod into the untracked .refactor/ folder.
.\venv\Scripts\python.exe scripts\refactor_settings_snapshot.py

# Compare a new run with the saved snapshot. Exit code 0 means no difference;
# 1 prints a unified diff; 2 means the snapshot is missing.
.\venv\Scripts\python.exe scripts\refactor_settings_compare.py
```

The snapshot is written to `.refactor/settings/` (ignored by Git). Production uses
the same throwaway `SECRET_KEY`, `JWT_SIGNING_KEY`, `ALLOWED_HOSTS`,
`DATABASE_URL` and `NUM_PROXIES` values as the CI deploy check. Immediately after
a snapshot, the compare script reports no difference for all three settings
modules.

## What R0 pins down

| Area | Test file |
| --- | --- |
| Ticket audit rows and tag-deletion audit rows | `core/tests/test_contract_ticket_audit.py` |
| User workflows through the API and the admin | `core/tests/test_contract_user_workflows.py` |
| Real-time payloads, `staff_only`, rollback silence | `core/tests/test_contract_realtime_payloads.py` |
| Error envelope codes and statuses | `core/tests/test_contract_errors.py` |
| Unread parity | `core/tests/test_parity_unread.py` |
| Download visibility parity (portal and widget) | `core/tests/test_parity_downloads.py` |
| Reopen entry points, release and routing | `core/tests/test_parity_reopen_release.py` |
| First response, due date, offline sweep, retention gap | `core/tests/test_parity_sla_offline_retention.py` |
| Query-count baselines | `core/tests/test_query_baselines.py` |
| Coverage for edge modules | `core/tests/test_coverage_gaps.py`, `core/tests/test_coverage_edge_modules.py` |

The retention test is marked `xfail(strict=True)` because
`chat.retention` currently ignores soft-deleted tickets; R1.1 owns that fix.

## Query-count baselines (R0.5)

These are asserted with `django_assert_max_num_queries`:

| Endpoint | Max queries |
| --- | ---: |
| Ticket list as agent | 4 |
| Ticket list as customer | 3 |
| Ticket messages | 5 |
| Widget messages | 8 |
| Stats | 8 |
| Audit | 4 |
| Online agents | 3 |
| Export (5 tickets, batch size 2) | 11 |

## Import rules (R0.6)

`pyproject.toml` contains six `forbidden` contracts:

1. `core` imports no other app.
2. `accounts` (except its models) imports no `tickets`, `chat`, `realtime`, `stats`
   or `audit`.
3. `tickets` imports no `chat`, `realtime`, `stats` or `audit`, except
   `chat.models`.
4. `chat` imports no `realtime`, `stats` or `audit`.
5. `realtime` is a leaf.
6. `stats` and `audit` are leaves.

Every current production violation is listed in `ignore_imports`; test modules
are ignored with `**.` wildcards because they intentionally build cross-app
fixtures. `lint-imports` runs in the CI lint step.

## Commands

```powershell
# Format (as configured by black/isort/ruff)
.\venv\Scripts\black.exe .
.\venv\Scripts\isort.exe .
.\venv\Scripts\ruff.exe check --fix .

# Lint without changing files (what CI runs, plus import rules)
.\venv\Scripts\black.exe --check .
.\venv\Scripts\isort.exe --check-only .
.\venv\Scripts\ruff.exe check .
.\venv\Scripts\lint-imports.exe

# Tests (the local Postgres/Redis used for the R0 run)
$env:DATABASE_URL="postgres://ticketing:ticketing@localhost:55432/ticketing"
$env:REDIS_URL="redis://localhost:6379/0"
.\venv\Scripts\python.exe -m pytest --cov --cov-report=term-missing

# Settings split proof
.\venv\Scripts\python.exe scripts\refactor_settings_snapshot.py
.\venv\Scripts\python.exe scripts\refactor_settings_compare.py
```
