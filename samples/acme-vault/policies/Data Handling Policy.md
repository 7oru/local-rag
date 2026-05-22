---
owner: security
product: Atlas CRM
security_level: restricted
tags:
  - policy
  - security
  - data
---

# Data Handling Policy

## Restricted Customer Data

Restricted customer data includes raw API keys, access tokens, payment information, private attachments, security questionnaires, legal contracts, and any customer-provided secrets. #security #restricted_data

Restricted data must stay in approved Acme storage systems. It must not be pasted into Slack, external ticket comments, public docs, or external LLM providers.

## External Model Boundary

External OpenAI-compatible models may receive only approved public or internal context. Before using an external model for a customer-specific answer, remove restricted identifiers and confirm the customer's data processing agreement.

If the user asks "哪些客户数据不能发给外部模型？", answer from this policy and cite this source.

中文检索提示：客户数据 不能 发给 外部模型 的范围包括 raw API keys、access tokens、payment information、private attachments、security questionnaires、legal contracts 和 customer-provided secrets。

## Related Runbooks

When restricted data appears in an incident, pause automation and notify Security Review. For P1 support flow, see [[policies/Support Escalation Policy]].
