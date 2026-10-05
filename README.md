<p align="center">
  <img src="assets/readme/contral.svg" alt="Contral — AI control layer" width="480">
</p>


<p align="center">
  <strong>Control what your AI can access, share and spend.</strong><br>
  Built for the Goldman Sachs challenge at HackYeah 2026.
</p>

Contral sits between an agent and its tools. It checks permissions, redacts sensitive data, assesses suspicious instructions, reserves provider costs and records what actually executed. An operator dashboard brings requests, decisions, budgets, policy changes and audit history into one place.

## How it works

- **Access control:** server-owned identities, roles and client scopes; unauthorized documents are blocked before reading.
- **Data protection:** local Presidio and secret rules mask sensitive values before they reach either AI provider and filter generated output.
- **Semantic checks:** TypeSafe Jev assesses instruction override and data exfiltration risk. A failed check stops generation; AI cannot override access rules.
- **Resource control:** SQLite reservations track task, user and global budgets, request quotas and concurrency. Uncertain provider costs remain reserved after a timeout or restart.
- **Artifact admission:** a trusted manifest, SHA-256 threat feed and strict JSON validation reject altered, blocked and unsupported artifacts without deserializing them.
- **Auditability:** versioned policy/feed, per-adapter execution status, request history and JSONL export.

The stack is Python 3.12, FastAPI, Pydantic, SQLite and a browser dashboard. Jev (`jev-1.13.0`) assesses risk; OpenAI Luna (`gpt-6-luna`) generates summaries. All included documents and artifacts are synthetic.

## Run locally

Requires [uv](https://docs.astral.sh/uv/), Git, Make and internet access for the initial installation. Python and both spaCy language models are installed from the lockfile.

```sh
git clone https://github.com/SzymonTyburczy/GoldmanSachsHackaton.git
cd GoldmanSachsHackaton
make setup
```

Setup creates `.env`, generates local bearer tokens, initializes SQLite and activates the default policy and feed. For document reads and AI summaries, add your own provider keys to `.env`:

```dotenv
OPENAI_API_KEY=your-openai-api-key
TYPESAFE_API_KEY=your-typesafe-api-key
```

```sh
make dev
```

Open the [dashboard](http://127.0.0.1:8000) or the [interactive API docs](http://127.0.0.1:8000/docs). Sign in using `CONTROLPROOF_TOKEN_ADMIN` from your local `.env` to access all operator views. Analyst and reviewer tokens provide restricted sessions. Tokens stay in the browser tab's memory.

**Without provider keys:** the dashboard, configuration, artifact admission and offline tests work. Document operations require Jev; summaries also require OpenAI. Missing keys produce a denial, never a simulated AI result.

## Try the demo

1. Sign in as admin and create a task for `client-a`.
2. Run **Admit template**. Block its returned hash from the result panel, then run it again to see the feed change take effect. **Admit tampered** and **Admit non-JSON** demonstrate artifact rejection.
3. With provider keys configured, try **Read A**, **Read B (other client)**, **Summarize A**, **PII in prompt** and **Prompt injection**. Inspect the decision and which adapters ran.
4. Change a policy in the dashboard and inspect the resulting audit events, budget balances and JSONL export.

## Configure and verify

Edit [`config/policy.json`](config/policy.json) for role/tool permissions, allowed fields, redaction, semantic threshold, model settings, pricing and resource limits. Edit [`config/threat-feed.json`](config/threat-feed.json) for artifact blocks. Run `make reload-config` to validate and activate changes, or update them in the admin dashboard. Active versions are stored in SQLite; editing a file alone does not change a running policy.

```sh
make check                  # Lint and formatting
make test                   # Offline tests; provider network access is blocked
make benchmark              # Offline component timings
make test-live              # Real provider checks and 12-case Jev evaluation
make benchmark GATEWAY=1    # Real end-to-end gateway measurements
```

Live commands require provider keys and incur API charges. Saved evaluation and benchmark reports appear in the dashboard; `make test` does not save a dashboard report.

## Human in the loop

Medium-risk requests wait in a persistent review queue in the dashboard. In [`config/policy.json`](config/policy.json), a Jev risk score below 0.50 continues automatically, 0.50 up to (but excluding) 0.80 returns `REQUIRE_APPROVAL`, and 0.80 or more blocks. `review_threshold` must be lower than `block_threshold`; `null` disables the queue. An older active policy without this field keeps its previous behaviour. After updating the code, restart `make dev` (SQLite migrates automatically from v1 to v2), then in the admin dashboard activate `semantic.review_threshold=0.5` and `semantic.review_timeout_seconds=900`, keeping the rest of the configuration. Use `make reload-config` instead if `config/` is the intended source of the current policy and feed.

1. The analyst sends a regular `POST /v1/execute`. A Jev score in the review band pauses the document release or summary generation and returns a `review_id`.
2. In a second tab, sign in with `CONTROLPROOF_TOKEN_REVIEWER_A` (or the admin token). The **Reviewer inbox** shows the masked assessed input with **Approve / Block** buttons. Notification is the inbox refreshing every 2 seconds; no email or SMS is sent.
3. Approve resumes exactly that operation after re-checking access, the document and the configuration; the budget and output filter still apply. Block ends it without calling Luna. The analyst's tab fetches the result automatically. The decision audit records the `reviewer_id`.

An approval expires after 15 minutes, can be used once and cannot be granted to oneself. A change to the document, policy or feed requires a new assessment. A restart keeps pending requests; an execution interrupted after approval becomes `UNKNOWN` and is not retried automatically. The queue stores only the masked prompt and document plus SHA-256 hashes for comparison, never raw values.

API: `GET /v1/reviews` (reviewer/admin, client-scoped), `GET /v1/reviews/{id}`, `POST /v1/reviews/{id}/decision` with `{ "schema_version": 1, "decision": "approve" }` or `"block"`, and `GET /v1/requests/{id}` (owner/admin). The last endpoint and a repeat of the original idempotency key return the current result.

Verify the flow with `uv run pytest tests/gateway/test_human_review.py -q`. These tests use explicit offline providers and do not measure real Jev accuracy.

This release targets a local, single-process demonstration. It protects calls routed through its adapters; semantic detection and pattern-based redaction do not guarantee detection of every attack. Demo identities and supported adapters are defined in code, while policy values are configurable.
