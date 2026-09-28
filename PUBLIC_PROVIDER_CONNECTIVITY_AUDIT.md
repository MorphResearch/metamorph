# Public provider connectivity audit

Scope: diagnose only the first public-calibration connection failure. No chat or
completion request was sent for this audit. The failed public run at
`artifacts/experience_value/public_calibration/e0-05418a6dd81a40f89db5c55ee83ea05f/`
is unchanged.

`study_kind=development_public_calibration`

`included_in_primary_analysis=false`

## Preserved failure evidence

At `2026-09-22T21:33:36.560913+08:00`, `dev-1-f0` emitted exactly one
`provider.request_started` event for `deepseek-v4-pro` against
`https://api.deepseek.com`. At `2026-09-22T13:33:38.726845+00:00`, it emitted
`provider.request_failed` with `error_type=APIConnectionError` and message
`Connection error.` No `provider.request_finished`, response usage, cache
information, SQL action, file action, native evaluation, or paid evaluator
request followed. The ledger remains one USD `0.01989504` conservative
reservation with `billing_unknown=true`; it is not an invoice or confirmed
charge. The consumed authorization remains consumed.

The original event did not include the exception's `__cause__` or `__context__`.
Therefore the deepest cause for that historical attempt is **UNKNOWN** and cannot
be reconstructed without another completion request, which this audit did not
make.

## A/B environment comparison

| Property | A: successful Atomic run | B: public calibration failure |
| --- | --- | --- |
| Interpreter | project `.venv`, CPython 3.10.5 | CL-Bench `.venv-database-exploration`, CPython 3.13.15 |
| OpenSSL | OpenSSL 1.1.1n (15 Mar 2022) | OpenSSL 3.5.8 (25 Aug 2026) |
| `openai` | 3.6.0 | 2.16.0 |
| HTTP runtime | `httpx2` embedded by the SDK; standalone `httpx` distribution unavailable | `httpx` 0.28.1 |
| LiteLLM | unavailable | 1.81.6 |
| certifi | unavailable | 2026.7.22, `.../.venv-database-exploration/lib/python3.13/site-packages/certifi/cacert.pem` |
| client SSL context | `truststore._api.SSLContext`, `CERT_REQUIRED`, hostname checking | standard verified context; 121 CA certificates |
| base URL | `https://api.deepseek.com` | `https://api.deepseek.com` |
| model / thinking | `deepseek-v4-pro`, enabled / low | `deepseek-v4-pro`, enabled / low |
| request timeout | 30 seconds | 45 seconds |
| SDK retry at actual request | 0 | 0 (`with_options(max_retries=0)`) |
| environment proxies | HTTP/HTTPS/ALL/NO proxy absent | HTTP/HTTPS/ALL/NO proxy absent |
| SDK HTTP proxy state | `trust_env=true`, explicit proxies `None` | `trust_env=true`, explicit proxies `None` |

`scutil --proxy` returned an empty dictionary. Thus neither environment proxy
variables nor a configured macOS system proxy were present for httpx to inherit.
No credentials were read or recorded. Both construct-only clients preserved the
exact base URL without an appended `/v1`, provider rewrite, or changed path.
The SDK client defaults advertise two retries, but the experiment's configured
request path explicitly binds `max_retries=0`; the failed attempt had no retry.

Atomic evidence from
`artifacts/experience_value/e0-e98ad111fe8849c4bca6dff4655c6c74/` shows its
first request completed successfully in about 2.02 seconds and its manifest
records the same base URL, provider, model, thinking mode, and zero SDK retry.

## Zero-completion network checks

All checks below used no API key and sent no model request. The HTTP check was a
credential-free `HEAD /` to the API root, which returned the expected
unauthorized response rather than invoking inference.

| Check | A | B |
| --- | --- | --- |
| DNS `getaddrinfo(api.deepseek.com, 443)` | initially blocked by the execution sandbox; unrestricted diagnostic result: IPv4 `198.18.0.68`, no IPv6 | initially blocked by the execution sandbox; unrestricted diagnostic result: IPv4 `198.18.0.68`, no IPv6 |
| raw TCP/TLS | failed after 33.49 ms: `SSLCertVerificationError: self signed certificate in certificate chain` | succeeded after 28.45 ms: TLS 1.3, `TLS_AES_256_GCM_SHA384` |
| credential-free `HEAD /` | failed after 25.53 ms with the same certificate-verification error | succeeded after 131–133 ms, HTTP 401 `Authorization Required`, server `openresty` |

B's peer certificate had subject/SAN `api.deepseek.com` and issuer `TrustAsia DV
TLS RSA CA 2025`. The resolved `198.18.0.68` address is an intercepted/local
network routing address rather than a public DeepSeek address; that fact alone
does not establish a fault because B completed verified TLS and received the API
root response through it.

## APIConnectionError cause assessment

**CONFIRMED**

- The historical public run reached local `provider.request_started`, then the
  OpenAI SDK raised `APIConnectionError` before any provider response.
- B currently has working DNS, verified TLS, and non-inference HTTP reachability
  to the configured host, with no IPv6 alternative or environment/system proxy
  configured.
- A's raw stdlib TLS check now rejects a self-signed chain, while its Atomic
  client used `truststore` and successfully completed real requests on
  2026-09-21. This is a trust-store implementation difference, not evidence that
  B has a certificate failure.

**SUPPORTED, not confirmed**

- The one B failure was likely transient or specific to the chat-completions
  connection path at 21:33 (for example an egress/intercept disruption), rather
  than a persistent B DNS/TLS/API-root configuration error. The later verified
  B checks support this, but cannot prove the state at the earlier instant.

**UNKNOWN**

- The original `APIConnectionError`'s deepest `ConnectError`, TLS error, DNS
  error, proxy error, or timeout cause was not recorded and cannot be inferred
  from the top-level string. Testing `/chat/completions` would be needed to
  distinguish request-path causes, and is prohibited for this audit.
- No conclusion about provider billing is possible because no usage response or
  invoice was received.

## Minimal diagnostic-only change and next step

`experiments/experience_value/live.py` now records a redacted ordered exception
chain (`class`, `message`, `cause/context`) inside a future
`provider.request_failed` event. It does not change endpoint construction,
TLS verification, proxy selection, timeout, retry count, reservation logic, or
request dispatch. This logging was added after the failed run and therefore does
not alter its preserved evidence.

No TLS/proxy/code fix is supported by the evidence. Before any future, separately
authorized batch, the minimal operational check is a credential-free B TLS plus
`HEAD /` smoke in the intended network context. A new chat-completions smoke or
batch requires a new explicit authorization; none was created here.
