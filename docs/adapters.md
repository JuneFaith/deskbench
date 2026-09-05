# Adapter contracts

Adapters isolate ServiceDeskBench from systems under test. Core contracts never
import Tix models; the HTTP adapter converts public JSON responses into
`CanonicalState` and `CanonicalTrace` evidence.

## Tix HTTP black-box MVP

`TixHttpAdapter` treats Tix as an external service and uses only public API
routes. It accepts an existing bearer token or logs in with a username and
password. `ticket_id` is stored in `RunHandle.run_id`; `thread_id` is the
approval resume handle returned by ticket detail.

| Operation | Public endpoint | Contract |
| --- | --- | --- |
| Login | `POST /auth/login` | Requires `access_token` |
| Create | `POST /tickets` | Accepts `202`; requires `ticket_id` |
| Detail | `GET /tickets/{ticket_id}` | Requires `ticket` object; retains `events` |
| Resume | `POST /tickets/{ticket_id}/resume` | Sends `thread_id`, `action`, `actor`, `comment` |
| Transition probe | `POST /tickets/{ticket_id}/transition` | Returns rejection evidence rather than assuming success |
| PATCH probe | `PATCH /tickets/{ticket_id}` | Returns rejection evidence rather than assuming success |

`wait_for_status()` polls detail responses until a bounded deadline. The
canonical state maps status, category, priority, urgency, severity, impact,
assignee, resolution, review state, and thread id. Event records map transition
status and actor fields while preserving detail, timestamps, ticket IDs, and
unknown fields under `raw`.

`HttpAdapterError` retains status code, endpoint, server `code`, detail, and a
classification (`http`, `transport`, `schema`, `timeout`, or `business`).
HTTP 200 only means the transport request succeeded; it does not establish that
a requested business transition succeeded. When Tix returns HTTP 200 with an
internal `result.error` in the graph execution payload, `HttpAdapterError`
classifies the failure as `business`.

### Asynchronous submission and multi-stage approval lifecycle

Tix ticket processing is asynchronous and may traverse multiple approval stages
(e.g., dispatch approval followed by resolution review):

1. **Submission and interrupt discovery**: Upon `POST /tickets`, Tix returns
   HTTP 202 with `ticket_id`. The adapter's `submit()` polls ticket detail
   within a bounded window (`_discover_interrupt`) to observe the first
   interruption before handing control to the runner.
2. **Resume and interrupt chaining**: `resume()` submits approval actions to
   `POST /tickets/{ticket_id}/resume` with `thread_id`, `action`, `actor`, and
   an optional comment. It parses the returned `GraphRunResponse`, strictly
   validating consistency between `completed` and `interrupted` states, ensuring
   ticket ID matches, and updating `RunHandle` with the next stage's `thread_id`
   and interruption flag.
3. **Approval lock probes**: During approval wait states, `transition_probe()`
   and `patch_probe()` test whether out-of-band transitions or modifications are
   properly locked out. Both return `HttpProbeResult` preserving the actual HTTP
   status code (e.g., 409 Conflict or 422 Unprocessable Entity), error code, and
   detail payload for invariance scorers.

`cleanup()` closes an adapter-owned HTTP client and deliberately sends no
request. Tix has no public `DELETE /runs` or benchmark cleanup endpoint.
Isolation and deletion are deployment responsibilities, not Adapter operations.
The HTTP MVP may run against a shared development deployment; in that mode the
created ticket remains in the shared database and the result does not prove
isolation or automatic cleanup.

## Other adapters

The existing Graph and retrieval adapters remain protocol-level components and
are not claimed as real Tix integration in this MVP. Their tests use injected
local collaborators and should not be confused with deployment-backed evidence.
