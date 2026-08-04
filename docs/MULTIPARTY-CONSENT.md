# Multi-party consent

*Gating a frame that contains more than one person — without becoming a surveillance system to do it.*

## The problem

The class gate decides perception by **class**: "humans — allowed" or "humans —
denied." A real space doesn't work that way. A frame can hold several people, and
some may have agreed to be recorded while others have not. "Alice opted in, Bob
didn't" is not expressible as a property of the class *human*; it is a property of
*each person in the frame*. This is the gap the conscience's honest-limits note
names (§4/§6): semantic consent is not expressible by class.

## The trap in the obvious solution

The obvious way to answer "did this person consent?" is to **recognize** the
person — run face recognition, match against a roster, look up their status. That
is a surveillance capability *strictly worse* than the one the conscience exists
to constrain: to decide whether to record anyone, you would first identify
*everyone* in frame, consented or not. A privacy body cannot check consent by
building the exact identification pipeline it is supposed to make unnecessary.

## The resolution: consent is a token the subject presents

Consent here is **affirmative, opt-in, and keyed to a token the subject presents**
— a BLE beacon, a badge, a scanned code — **not an identity the system derives.**
The system never learns *who* someone is. It checks only whether a valid consent
**token** accompanies them. A person with no token is simply not consented.

Three consequences fall out, all fail-closed:

1. **Opt-in, never opt-out.** No token ⇒ not consented. A person is never recorded
   because they failed to object; recording requires their affirmative grant.
2. **No recognition.** Absent a presented token there is nothing to look up, and
   the system is not built to look anyone up. Privacy is the default state.
3. **The unconsented are never singled out.** Under the default policy, one
   un-tokened person refuses the *whole frame*. The system reports a count, not a
   list — a "who didn't consent" roster would itself be surveillance.

This dissolves the trap: you look for a consent *signal*, you do not identify
*people*.

## What a grant is

A consent grant (`ConsentGrant`) is:

- **Scoped** to a `purpose` — consent to "record for the wildlife study" is not
  consent to "livestream." A decision must match the purpose.
- **Expiring** — `expires_at_ms` is a hard bound; consent is not forever. An
  expiry of `0` is treated as *already expired*, so an operator cannot mint
  eternal consent by leaving the field unset.
- **Revocable** — a revoked grant never consents, effective immediately.

Validity fails closed on every axis: unknown token, wrong purpose, past expiry, or
revoked all read as **not consented**.

## The frame decision

`decide_frame(subjects, ledger, restricted_class, purpose, now, policy)` checks
only subjects whose class is the restricted one (`human` by default) — wildlife
and other non-restricted classes never need a token. Each restricted subject is
consented iff it presented a token that is a valid grant for the purpose at the
current time. Then:

- **`RequireAll`** (default, most conservative): if *any* restricted subject lacks
  consent, refuse the whole frame. Never stores a frame someone in it didn't agree
  to; never singles anyone out.
- **`Redact`**: keep the frame but return the indices of the un-consented subjects
  to blank before storage.

## Running it

A policy-authoring / testing tool:

```
oh-ben-claw consent-check --frame frame.json --ledger ledger.json \
    [--purpose record] [--policy require-all|redact]
```

- `frame.json`: a JSON array of `{class, consent_token?}` — the subjects detected
  in the frame (class as produced by the classifier; `consent_token` omitted or
  `null` for anyone who presented none).
- `ledger.json`: a JSON array of `{subject, purpose, expires_at_ms, revoked?}` —
  the consent grants. `subject` is the token, not a name.

The restricted class comes from `[conscience.classifier]` in config; `now` is the
wall clock. Worked samples: `crates/obc-conscience/examples/sample-consent-frame.json`
and `sample-consent-ledger.json` in the Oh-Ben-Claw repo.

## Honest limits (labeled, not solved)

- **Redaction needs localization.** `Redact` returns which subjects to blank, but a
  detector that can't localize per subject can't act on it — the caller must then
  treat `Redact` as `Refuse` (fail closed). The decision is honest about this; the
  capability is the body's.
- **A token is not a person's true will.** This checks that a valid consent token
  is present, not that consent was freely given, nor that the right person holds
  the token. Binding a token to a willing human — and preventing a coerced or
  borrowed one — is an out-of-band, physical-world problem this layer cannot close.
- **It does not stop an operator with physical control.** Like the rest of the
  conscience, it makes the ungated act explicit, effortful, and loggable — not
  impossible.

## Where it sits

This is the *second* consent layer. The class gate decides whether the class is
permitted at all (and with what retention/transmit); multi-party consent then
decides, among the humans actually in a permitted frame, whether *this frame* may
be captured given who presented consent. Wiring it into the live perception
ingest path (alongside `conscience_filter`) is the remaining integration step; the
decision function and its tests are in place.
