---
owner: product
product: Atlas CRM
security_level: internal
tags:
  - faq
  - product
---

# Atlas CRM FAQ

## Which exports are supported?

Atlas CRM supports CSV export for account summaries, opportunity metadata, activity logs, and support-ticket references. #export

It does not support exporting raw API keys, private customer attachments, payment data, or security review documents. When a customer asks for sensitive data export, route the request to Security Review and cite [[policies/Data Handling Policy]].

## Can Atlas CRM send data to external LLMs?

Atlas CRM can send approved prompt context to an external model only when the data classification is public or internal and the customer contract allows model processing. Restricted customer data must not be sent to external LLM providers.

## How should Support use Atlas CRM?

Support should link every P1 incident to an account record, attach the case timeline, and record the escalation owner. For incident handoff, follow [[policies/Support Escalation Policy]].
