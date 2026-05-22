---
owner: product
product: Atlas CRM
security_level: internal
tags:
  - product
  - atlas_crm
---

# Atlas CRM

Atlas CRM is Acme Corp's enterprise customer relationship platform for account management, support coordination, and revenue operations. #product #atlas_crm

## Core Capabilities

Atlas CRM supports account timelines, contact enrichment, task routing, customer health scores, and support ticket linking. It integrates with the internal event bus and the Support Console through the Atlas API.

## Data Export

Atlas CRM allows workspace administrators to export account summaries, activity logs, and non-sensitive opportunity metadata as CSV. The export job is asynchronous and appears in the Admin Console when complete.

Exports do not include raw customer secrets, private attachments, payment tokens, or security questionnaires. Those fields are governed by [[policies/Data Handling Policy]] and must stay inside approved storage.

中文检索提示：Atlas CRM 数据导出 限制 包括不能导出 raw customer secrets、private attachments、payment tokens 和 security questionnaires。

## Related Notes

For common product questions, see [[products/Atlas CRM FAQ]]. For customer issue triage, see [[support/Common Customer Issues]].
