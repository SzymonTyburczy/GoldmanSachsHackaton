# ContrAl developer commands. Live checks make real, billable provider requests.

UV ?= uv
HOST ?= 127.0.0.1
PORT ?= 8000
ITERATIONS ?= 100
# Load .env for app commands only when it exists. Tests never load it.
WITH_ENV = $$(test -f .env && echo --env-file=.env)

.DEFAULT_GOAL := help
.PHONY: help setup dev check format test test-live verify reload-config benchmark

help:
	@echo "setup      install locked dependencies, create .env, fill empty demo tokens, initialise the"
	@echo "           database, activate config/ if nothing is active, check the local Presidio engine"
	@echo "dev        run the API and panel on http://$(HOST):$(PORT) (one process, one worker)"
	@echo "check      Ruff lint and format check"
	@echo "format     apply Ruff formatting and safe fixes"
	@echo "test       offline tests; network to TypeSafe and OpenAI is blocked"
	@echo "test-live  paid Luna smoke test and 12-sample Jev evaluation (requires local API keys)"
	@echo "verify     check + test + test-live"
	@echo "benchmark  100 offline measurements; use LIVE=1 for provider and GATEWAY=1 for full gateway cases"
	@echo "reload-config  validate config/policy.json and config/threat-feed.json, activate changes"

setup:
	$(UV) sync --locked
	@test -f .env || { cp .env.example .env && chmod 600 .env && echo "Created .env from .env.example; fill in local values."; }
	$(UV) run python -m app.auth .env
	$(UV) run $(WITH_ENV) python -m app.db
	$(UV) run $(WITH_ENV) python -m app.policy seed
	$(UV) run python -m app.pii.engine

dev:
	$(UV) run $(WITH_ENV) uvicorn --factory app.main:create_app --host $(HOST) --port $(PORT)

check:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

test:
	$(UV) run pytest -m "not live"

test-live:
	$(UV) run $(WITH_ENV) python -m scripts.check_live_credentials
	$(UV) run $(WITH_ENV) pytest -m live
	$(UV) run $(WITH_ENV) python -m scripts.evaluate

verify: check test test-live

benchmark:
	@if [ "$(LIVE)" = "1" ] || [ "$(GATEWAY)" = "1" ]; then \
		$(UV) run $(WITH_ENV) python -m scripts.check_live_credentials && \
		$(UV) run $(WITH_ENV) python -m scripts.benchmark \
			$(if $(filter 1,$(LIVE)),--live,) \
			$(if $(filter 1,$(GATEWAY)),--gateway-live,) \
			--iterations $(ITERATIONS); \
	else \
		$(UV) run $(WITH_ENV) python -m scripts.benchmark --iterations $(ITERATIONS); \
	fi

reload-config:
	$(UV) run $(WITH_ENV) python -m app.policy reload
