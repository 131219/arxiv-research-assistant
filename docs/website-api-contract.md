# Website Research API Contract

Status: Approved V1 target

## Purpose

Define the minimal public API contract for the standalone research
website before retrieval code is refactored or frontend development begins.

This contract describes public website behavior. It must not expose raw
Amazon Bedrock metadata, internal S3 locations, AWS exception details, or
implementation-specific retrieval fields.

## Endpoint

`POST /api/v1/research`

Request headers:

```text
Authorization: Bearer <access-token>
Content-Type: application/json
```

The initial backend proof uses a synchronous JSON response. Streaming is
outside the first contract and may be added later as a separate extension.

## Request

```json
{
  "question": "What approaches improve transformer attention efficiency?",
  "max_papers": 5
}
```

Fields:

- `question`: required string, 3 to 2000 characters after trimming
- `max_papers`: optional integer, defaults to 5, minimum 1, maximum 10

Unknown request fields are rejected.

## Success Response

HTTP status: `200 OK`

```json
{
  "request_id": "8b76a7c3-7e5e-4df3-8404-c70f991cc8a4",
  "question": "What approaches improve transformer attention efficiency?",
  "answer": "Researchers use sparse and hardware-aware attention methods [2606.04032].",
  "citations": [
    {
      "paper_id": "2606.04032",
      "arxiv_url": "https://arxiv.org/abs/2606.04032",
      "passage": "A relevant passage supporting the cited claim."
    }
  ]
}
```

Fields:

- `request_id`: opaque identifier used to correlate the response with backend logs
- `question`: trimmed question accepted by the API
- `answer`: grounded synthesis containing inline citations in `[paper_id]` form
- `citations`: citation records used by the answer
- `citations[].paper_id`: stable arXiv paper identifier
- `citations[].arxiv_url`: public HTTPS link to the paper
- `citations[].passage`: retrieved evidence supporting the citation

The response does not expose internal retrieval scores, archive IDs, S3
locations, raw Bedrock metadata, model identifiers, or prompts.

## Response Invariants

- Every inline citation in `answer` uses the exact `[paper_id]` format.
- Every inline paper ID maps to exactly one record in `citations`.
- Every record in `citations` is referenced at least once in `answer`.
- Citation records are unique by `paper_id`.
- Citation order follows the first appearance of each paper ID in `answer`.
- Retrieved papers not cited by the final answer are not returned as citations.
- `question` contains the normalized, trimmed request question.
- `request_id` is opaque and must not encode user or infrastructure details.

If the retrieved evidence is insufficient, the API returns `200 OK` with
an answer that clearly states the limitation and an empty `citations` list.
It must not invent an answer or citation.

## Error Response

All errors use the same public shape:

```json
{
  "request_id": "8b76a7c3-7e5e-4df3-8404-c70f991cc8a4",
  "error": {
    "code": "INVALID_REQUEST",
    "message": "question must contain between 3 and 2000 characters"
  }
}
```

Public errors:

| HTTP status | Code | Meaning |
|---|---|---|
| `400` | `MALFORMED_REQUEST` | Request body is not valid JSON. |
| `401` | `AUTHENTICATION_REQUIRED` | Access token is missing or invalid. |
| `403` | `ACCESS_DENIED` | Authenticated identity is not allowed to use the API. |
| `415` | `UNSUPPORTED_MEDIA_TYPE` | Request does not use `application/json`. |
| `422` | `INVALID_REQUEST` | Request fields violate the public contract. |
| `429` | `RATE_LIMITED` | User or client has exceeded an allowed usage limit. |
| `500` | `INTERNAL_ERROR` | An unexpected internal failure occurred. |
| `503` | `RESEARCH_UNAVAILABLE` | Retrieval or synthesis could not safely complete. |

A `429` response includes a `Retry-After` header when the backend knows
when another request may be attempted.

A `503` response may be returned after bounded retries for timeouts,
throttling, unavailable dependencies, or synthesis that fails citation
validation. The API does not return a partial or ungrounded answer.

Public error messages must not contain AWS request details, service names,
resource identifiers, exception strings, stack traces, prompts, model
output, or credentials.

## Authentication

`POST /api/v1/research` requires an OAuth 2.0 Bearer access token.

The browser sends:

```text
Authorization: Bearer <access-token>
```

The API does not accept AWS credentials or Cognito ID tokens from the
browser.

Amazon Cognito is the target identity provider for the initial website.
The public API contract does not require token validation to occur in a
specific layer; validation may be enforced by AWS infrastructure or API
middleware.

Authentication and authorization must complete before Knowledge Base
retrieval or model invocation begins.

- Missing, malformed, expired, or otherwise invalid access tokens return
  `401 AUTHENTICATION_REQUIRED`.
- A valid identity that is not authorized to use the research endpoint
  returns `403 ACCESS_DENIED`.

Authentication failures use the same public error shape and must not
expose token contents, claim values, validation internals, or Cognito
resource identifiers.

## Request Validation

The request body must be one JSON object using the `application/json`
media type. Standard media-type parameters such as `charset=utf-8` are
allowed.

Validation rules:

- Leading and trailing whitespace is removed from `question`.
- The normalized `question` must contain between 3 and 2000 characters.
- Internal whitespace and Unicode text are preserved.
- An empty or whitespace-only `question` is invalid.
- `max_papers` must be a JSON integer between 1 and 10.
- Numeric strings, floating-point values, booleans, and `null` are invalid
  for `max_papers`.
- Values outside the allowed range are rejected rather than clamped.
- Unknown request fields are rejected.

Malformed JSON returns `400 MALFORMED_REQUEST`.

A request with an unsupported or missing content type returns
`415 UNSUPPORTED_MEDIA_TYPE`.

A well-formed JSON request that violates field rules returns
`422 INVALID_REQUEST`.

## Response Headers

Every success and error response includes:

```text
Content-Type: application/json
X-Request-ID: <opaque-request-id>
Cache-Control: no-store
```

`X-Request-ID` matches the `request_id` field in the JSON body and may be
provided to support for request tracing.

Responses must not be stored by browsers, shared proxies, or CDNs.

CORS policy is outside this contract until the website origin and
deployment architecture are selected. Production CORS must use an
explicit origin allowlist rather than a wildcard.

## Client Retry Behavior

Clients must not automatically retry `400`, `401`, `403`, `415`, or
`422` responses without changing the request or authentication state.

Clients may retry `429` and `503` responses using bounded exponential
backoff and respecting `Retry-After` when present.

Each retry is a new research operation with a new `request_id`. The first
contract does not provide idempotency keys or guarantee suppression of
duplicate model work.

## V1 Non-Goals

The first website backend contract does not include:

- streaming or Server-Sent Events
- asynchronous research jobs or polling
- idempotency-key storage
- anonymous access
- conversation history or multi-turn research
- saved searches, collections, or user libraries
- category, author, date, or corpus filters
- pagination
- PDF uploads
- corpus ingestion or administration
- frontend-specific presentation fields
- public model selection or prompt controls

These capabilities require separate product and architecture decisions
after the synchronous authenticated backend path works end-to-end.

## Current and Planned Implementation State

This document defines a target public contract. The
`POST /api/v1/research` endpoint does not exist yet.

Current retrieval orchestration remains inside the MCP adapter. The shared
retrieval service described in the project roadmap is a planned extraction,
not an existing component.

The next implementation milestones are:

1. extract the existing MCP retrieval behavior into a typed shared service
2. keep the MCP adapter compatible by delegating to that service
3. add website request and response models matching this contract
4. add website-only synthesis and citation validation
5. expose the endpoint only after the backend path passes end-to-end tests

The existing `/ask` endpoint is experimental and is not the public website
contract. The existing ChatGPT MCP path remains unchanged while this website
backend is built.

## Contract Acceptance Criteria

The contract is implemented only when automated tests prove all of the
following behavior:

- A valid request defaults `max_papers` to 5.
- Leading and trailing question whitespace is removed.
- Invalid JSON types, field bounds, and unknown fields are rejected.
- Authentication and authorization finish before retrieval or synthesis.
- A successful response matches the documented public fields and headers.
- No-evidence responses return `200 OK`, a clear limitation, and no citations.
- Every inline paper ID maps to exactly one returned citation.
- Every returned citation is used by the answer.
- Citations are unique and ordered by first appearance in the answer.
- Uncited retrieval candidates remain internal.
- Invalid or fabricated model citations never reach the client.
- Transient dependency failures return a sanitized `503` without a partial answer.
- Every error uses the documented public error shape and code.
- Success and error bodies match the `X-Request-ID` response header.
- Responses include `Cache-Control: no-store`.
- Raw AWS metadata, S3 locations, exception text, prompts, and model output are
  absent from public errors and citation records.

A real authenticated end-to-end test must also prove:

Question
→ website API
→ shared retrieval service
→ Amazon Bedrock Knowledge Base
→ website synthesis service
→ citation validation
→ contract-compliant response

Frontend development begins only after this backend acceptance path succeeds.

## Versioning Policy

Once `/api/v1/research` is released to clients, breaking request or response
changes require a new API version. Examples include renaming or removing fields,
changing field types, or changing the meaning of an existing error code.

Compatible additions may be made within V1 only when existing clients can safely
ignore them. Public fields must not be added merely to expose a new internal AWS
or model implementation detail.
