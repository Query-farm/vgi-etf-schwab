# vgi-etf-schwab — dev and test targets. `make help` lists them.
#
# SQL tests (test/sql/*.test) run through the published haybarn-unittest with the
# signed community `vgi` extension, over each transport (ci/run-integration.sh):
#   stdio   DuckDB spawns the worker per connection
#   launch  DuckDB starts the worker once on a unix socket and pools connections
#   http    the worker serves `--http`, as in Docker deploys
# One transport only: make test-sql TRANSPORTS=launch

HAYBARN_VERSION  ?= 2.0.1rc3
TOOLS            := $(CURDIR)/.tools
HAYBARN_UNITTEST := $(TOOLS)/bin/haybarn-unittest
WORKER           := $(CURDIR)/.venv/bin/vgi-etf-schwab-worker
TRANSPORTS       ?= stdio launch http
# test/sql/live.test hits Schwab and is gated on VGI_SCHWAB_LIVE (make test-live).
export EXPECTED_SKIP_REASONS := require-env VGI_SCHWAB_LIVE

.DEFAULT_GOAL := help
.PHONY: help build tools test test-unit test-sql test-live lint check

help: ## List the targets
	@awk 'BEGIN{FS=":.*## "} /^[a-zA-Z_-]+:.*## /{printf "  %-10s %s\n",$$1,$$2}' $(MAKEFILE_LIST)

build: ## Install the worker and dev tools into .venv
	uv sync --locked --all-extras

tools: ## Install the pinned SQL test runner into .tools
	@test -x $(HAYBARN_UNITTEST) || { uv venv -q $(TOOLS) && uv pip install -q -p $(TOOLS) haybarn-unittest==$(HAYBARN_VERSION); }

test-unit: build ## Unit tests (pytest)
	uv run pytest -q

test-sql: build tools ## SQL tests through DuckDB over stdio, launch and http
	@set -e; for t in $(TRANSPORTS); do \
	  echo "== test/sql over $$t"; \
	  WORKER=$(WORKER) HAYBARN_UNITTEST=$(HAYBARN_UNITTEST) TRANSPORT=$$t PYTHON="uv run --no-project python" ci/run-integration.sh; \
	done

test-live: build tools ## Live Schwab checks too (test/sql/live.test), over stdio
	VGI_SCHWAB_LIVE=1 WORKER=$(WORKER) HAYBARN_UNITTEST=$(HAYBARN_UNITTEST) TRANSPORT=stdio ci/run-integration.sh

test: test-unit test-sql ## Unit + SQL tests (offline)

lint: build ## Static checks (mirrors CI's lint job)
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy vgi_etf_schwab/

check: lint test ## Everything CI runs
