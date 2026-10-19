# PM-005: Expired TLS Certificate on API Gateway

> Incident ID: INC-2026-0814
> Date: 2026-08-14
> Severity: SEV-2
> Affected services: API Gateway, Payment Service
> Status: Resolved
> Document type: Synthetic incident postmortem

## 1. Summary

On 2026-08-14, an API Gateway certificate expired before its replacement was
deployed. Clients and an internal service began rejecting TLS connections to the
gateway. Application instances remained running, but affected requests failed
during connection establishment.

All incident details and metrics in this postmortem are fictional.

## 2. Customer impact

Approximately 18% of requests to the affected gateway endpoint failed for
21 minutes. Requests routed through an unaffected internal path continued to work.
There was no evidence that application data was corrupted.

## 3. Timeline

- 06:00 UTC — Certificate monitoring generated a warning that was not acknowledged.
- 08:30 UTC — The gateway certificate reached its expiration time.
- 08:32 UTC — TLS handshake failures increased sharply.
- 08:36 UTC — Responders confirmed the served certificate was expired.
- 08:42 UTC — The approved certificate renewal was completed.
- 08:48 UTC — The renewed certificate was deployed to gateway instances.
- 08:53 UTC — TLS verification and request health checks passed.

## 4. Root cause

The certificate renewal workflow had created a replacement certificate, but its
deployment step had not completed. The gateway continued serving the expired
certificate because the renewal process did not require a successful deployment
confirmation.

## 5. Contributing factors

The expiry warning was routed to a low-priority notification channel. Certificate
inventory did not consistently map certificates to their deployed endpoints.
The deployment dashboard tracked renewal jobs but did not verify the certificate
actually served by each gateway instance.

## 6. Resolution

Responders verified the certificate subject, hostname, issuer chain, and expiration
timestamp. They deployed the approved renewed certificate and checked the served
certificate from the affected endpoint. They then verified successful TLS handshakes
and normal request rates.

The response followed `../runbooks/RB-005-certificate-expiry.md`. Certificate validation was
not disabled as a workaround.

## 7. Preventive actions

- Alert on certificate expiry with a defined response window and clear ownership.
- Verify deployed certificate validity after every renewal.
- Maintain an inventory mapping certificates to service endpoints.
- Test renewal and deployment as one end-to-end workflow.
- Alert when renewal succeeds but deployment confirmation is missing.

## 8. Lessons learned

A successful certificate-renewal job does not prove that the new certificate is
being served. Responders must inspect the live endpoint and distinguish expiration
from hostname, trust-chain, or clock-related failures. Disabling TLS verification
would conceal the symptom while weakening connection security.
