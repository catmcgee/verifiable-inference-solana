# Payment gateway design

## Active boundary

Payment is no longer implemented inside `server/main.py`. The inference origin
has one generation implementation and accepts two access mechanisms:

- a short-lived, signed, HttpOnly browser session created with the operator's
  test access code; or
- an `Authorization: Bearer` credential injected by the pay gateway only after
  it accepts an x402 payment.

The static browser never contains or persists the access code. Free registry,
attestation, and receipt reads remain public. The origin returns `401`, not a
payment challenge, when generation is requested without either credential.

`payskill/inference.yaml` is generated from `models.yaml` and runs under the
official pay CLI. Its public endpoint returns a standard x402
`PAYMENT-REQUIRED` challenge, verifies/settles the payment, injects the origin
bearer token, and proxies the same OpenAI-compatible request. The runtime spec
uses `x402-upto`: a client authorizes a ceiling, the proxy observes the final
OpenAI usage object, settles the measured per-model token cost, and refunds the
remainder. Missing usage fails settlement instead of guessing a charge.
Paid requests currently require `stream: false` because the meter reads the
final JSON usage object. Authenticated browser sessions use the origin directly
and can stream SSE.

This refund behavior is the current pay 0.22 usage-metering mechanism. It does
not implement the older project requirement to charge
`prompt_tokens * input_rate + max_tokens * output_rate` with no refund. That
requirement remains unresolved unless the project deliberately chooses a
different, compatible gateway scheme.

## Generated pipeline

```text
models.yaml
  -> payskill/generate_runtime.py
  -> pay skills provider sync
  -> generated PAY.md + OpenAPI
  -> pay catalog check
```

Useful commands:

```sh
make pay-runtime
make pay-sandbox-test
make payskill
```

`make pay-sandbox-test` performs a real sandbox handshake: anonymous request
gets `402` + `PAYMENT-REQUIRED`, `pay --sandbox curl` signs and pays, the proxy
adds the bearer credential, and the test origin returns usage and a receipt.
Sandbox funds are ephemeral and are not mainnet funds.

## Legacy channel

The files under `server/x402/session.py`, `middleware.py`, and `chain.py`, plus
the Anchor payment-channel instruction, are retained as devnet experiment
evidence. `vinfer-session-v1` is not imported by the active server and is not
advertised by the public origin. It must not be described as x402 or MPP.

## Publication gate

Do not start a public gateway or publish the generated provider entry until:

1. a mainnet operator/recipient wallet is configured intentionally;
2. the generated runtime uses `network: mainnet` and a stable paid HTTPS host;
3. every paid response exposes the actual on-chain inference-receipt
   transaction, not only a signed local receipt ID;
4. every listed model is healthy on the deployed origin;
5. `pay catalog check ... --strict` passes with live probes; and
6. the x402-upto refund semantics are accepted as superseding the old
   no-refund requirement, or a compliant no-refund design is implemented.

The generator never publishes or opens a pull request.
