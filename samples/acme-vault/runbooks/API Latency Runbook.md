---
owner: sre
product: Atlas CRM
security_level: internal
tags:
  - runbook
  - api
  - latency
---

# API Latency Runbook

## Trigger

Use this runbook when Atlas API p95 latency is above 800 ms for 10 minutes or customer requests time out. #runbook #latency

## Immediate Checks

Check the API gateway error rate, regional saturation, queue depth, and Postgres connection pool usage. Compare the current deploy with the last known good release.

中文检索提示：API 延迟 升高 时 值班工程师 应该 检查 p95 latency、API gateway error rate、queue depth 和 Postgres connection pool。

## Mitigation

If latency is caused by read pressure, enable read-through cache for account timeline endpoints. If writes are blocked by database locks, coordinate with the database on-call and use [[runbooks/Postgres Incident Runbook]].

## Communication

For customer-visible impact, create a P1 or P2 according to [[policies/Support Escalation Policy]]. Include the p95 latency chart, affected endpoints, mitigation owner, and next update time.
