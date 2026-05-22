---
owner: sre
product: Atlas CRM
security_level: internal
tags:
  - runbook
  - postgres
  - database
---

# Postgres Incident Runbook

## Symptoms

Common Postgres incident signals include connection pool exhaustion, high lock wait time, replication lag, slow queries, and storage pressure. #postgres #database

## Triage

Check active sessions, top queries by total time, blocked transactions, index bloat, and replication health. Capture the timeline before changing configuration.

## Mitigation

For connection pool exhaustion, reduce API worker concurrency and restart only the affected service. For lock contention, identify the blocking PID and coordinate with the owning team before termination.

## Customer Updates

If Atlas CRM customers experience downtime or severe degradation, follow [[policies/Support Escalation Policy]] and document impact in Atlas CRM.
