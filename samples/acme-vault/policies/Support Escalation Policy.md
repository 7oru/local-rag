---
owner: support
product: Atlas CRM
security_level: internal
tags:
  - policy
  - support
  - escalation
---

# Support Escalation Policy

## P1 Escalation

A P1 incident is a production outage, data-loss risk, security-impacting bug, or customer executive escalation affecting Atlas CRM. #support #p1

For a customer P1 ticket, Support must acknowledge within 15 minutes, assign an escalation owner, notify the on-call engineer, and create a war-room thread. The escalation owner keeps the customer timeline updated every 30 minutes until mitigation.

中文检索提示：客户 P1 工单 应该 升级 到 escalation owner 和 on-call engineer，并创建 war-room thread。

## P2 Escalation

A P2 incident has major business impact but a workaround exists. Support should assign an owner within 1 business hour and link the relevant runbook.

## Required Artifacts

Every escalation must include customer account, severity, timeline, known impact, current mitigation, and next update time. If the issue is API latency, use [[runbooks/API Latency Runbook]].
