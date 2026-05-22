---
owner: support
product: Atlas CRM
security_level: internal
tags:
  - support
  - customer_issues
---

# Common Customer Issues

## Login and SSO

If a customer cannot log in through SSO, confirm the IdP metadata, clock skew, and user assignment. Escalate to Identity Engineering only after collecting SAML trace details. #support #sso

## Missing Account Timeline Events

When timeline events are missing, check whether the event bus consumer is delayed and whether the account integration has permission to write activity logs.

## API Timeout Complaints

For repeated API timeouts, collect endpoint, request ID, account ID, timestamp, and region. Then follow [[runbooks/API Latency Runbook]] and decide severity using [[policies/Support Escalation Policy]].

## Sensitive Data Requests

If a customer asks support to export secrets, attachments, payment data, or security questionnaires, decline direct export and cite [[policies/Data Handling Policy]].
