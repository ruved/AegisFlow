# RB-005: TLS Certificate Expiry

> Status: Current synthetic runbook
> Version: 1.0
> Owner: Platform Reliability
> Applies to: API Gateway and service-to-service HTTPS connections
> Last reviewed: 2026-10-16

## 1. Purpose

Use this procedure when HTTPS requests fail because a TLS certificate has
expired, is not yet valid, or cannot be validated by a client.

All domains, certificate dates, thresholds, and examples are fictional.

## 2. Symptoms

- TLS handshake failures increase suddenly.
- Clients report certificate-expired or certificate-validation errors.
- HTTPS health checks fail while application processes remain running.
- Failures affect clients using a particular hostname or certificate chain.
- Errors begin near a known certificate expiration date.

A TLS error does not automatically mean the certificate has expired.

## 3. Initial triage

1. Record the affected hostname, service, environment, and incident start time.
2. Capture the exact TLS error from an approved diagnostic.
3. Inspect certificate validity dates, hostname coverage, issuer, and chain.
4. Check system clock synchronization and recent certificate or proxy changes.
5. Determine whether failures affect all clients or only a particular trust store.

Do not paste private keys, credentials, or unredacted secret material into incident notes.

## 4. Diagnosis

### Expired certificate

Verify the certificate's not-after timestamp using an approved certificate
inspection tool and compare it with the current system time.

### Incomplete or untrusted chain

Check whether the presented chain contains the required intermediate certificates
and whether the client trusts the issuing certificate authority.

### Hostname mismatch

Compare the requested hostname with the certificate's subject alternative names.

### Clock skew

Check system time synchronization on the client and server. An incorrect clock
can make a valid certificate appear expired or not yet valid.

### Incorrect certificate deployment

Compare the certificate served by the endpoint with the intended certificate
version and recent configuration changes.

## 5. Mitigation

1. Confirm the failure mode before replacing a certificate.
2. If expiration is confirmed, follow the approved certificate renewal and
   deployment procedure.
3. Verify that the renewed certificate covers the required hostnames and has
   a valid chain.
4. If a recent certificate deployment introduced the failure, restore the
   last known valid configuration when safe.
5. Coordinate changes across load balancers and service instances to avoid
   inconsistent certificate presentation.

Never disable certificate validation as a workaround.

## 6. Verification

Verify from an approved client or diagnostic environment:

- The served certificate is within its validity period.
- Hostname validation succeeds.
- The certificate chain validates.
- TLS handshakes succeed for affected endpoints.
- HTTPS health checks and application requests recover.

Continue monitoring for inconsistent certificates across instances.

## 7. Rollback and escalation

Rollback a certificate configuration only when the previous certificate is
still valid and its private key remains appropriately protected. Escalate to
the certificate owner if renewal, chain validation, or key access is blocked.

## 8. Closure notes

Record the affected hostname, certificate validity information, confirmed
failure mode, renewal or rollback performed, verification evidence, and
follow-up actions. Never include private keys in the closure notes.
