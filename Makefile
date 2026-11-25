# Root Makefile: every gate runs locally (no CI service; plan › Test Strategy).
# `make help` lists the targets. Targets marked "planned" print the task that
# implements them and fail, so a missing gate is never mistaken for a pass.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

ROOT        := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
INGEST      := $(ROOT)/services/ingestion
UV          := uv run --project $(INGEST)
PYTEST      := $(UV) pytest -c $(INGEST)/pyproject.toml --rootdir $(ROOT)
FIRMWARE    := $(ROOT)/firmware
HOST_BUILD  := $(FIRMWARE)/test/host/build
IDF_PATH    ?= $(HOME)/esp/esp-idf-v5.4.4
IDF_EXPORT  ?= $(IDF_PATH)/export.sh
COMPOSE     := docker compose -f $(ROOT)/infrastructure/compose.yaml --env-file $(ROOT)/.env

SCENARIO ?= normal
SIM_ARGS ?=
DURATION ?= 10m
OUTAGE   ?= 10m

define planned
	@echo "make $@: planned, not implemented yet ($(1))" >&2; exit 1
endef

.PHONY: help
help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-30s %s\n", $$1, $$2}'

# ---- Setup -------------------------------------------------------------------

.PHONY: deps hooks
deps: ## Install the locked Python environment (services/ingestion/uv.lock)
	uv sync --project $(INGEST) --locked

hooks: deps ## Install the local pre-commit hooks
	$(UV) pre-commit install

# ---- Secrets and hygiene -------------------------------------------------------

.PHONY: secrets-scan lint deps-scan coverage
secrets-scan: ## Scan git history and the working tree for secrets (gitleaks)
	gitleaks git --redact --no-banner --config $(ROOT)/.gitleaks.toml $(ROOT)
	gitleaks dir --redact --no-banner --config $(ROOT)/.gitleaks-worktree.toml $(ROOT)
	@bad=$$(git -C $(ROOT) ls-files -- infrastructure/secrets | grep -v '/README.example.md$$' || true); \
	  if [ -n "$$bad" ]; then echo "secret files are tracked: $$bad" >&2; exit 1; fi; \
	  echo "PASS no tracked files in infrastructure/secrets/ besides README.example.md"

lint: secrets-scan ## ruff, mypy, clang-format, gitleaks
	cd $(ROOT) && $(UV) ruff check .
	cd $(ROOT) && $(UV) ruff format --check .
	cd $(INGEST) && uv run mypy
	git -C $(ROOT) ls-files -co --exclude-standard -- 'firmware/*.c' 'firmware/*.h' \
	  | (cd $(ROOT) && xargs -r clang-format --dry-run --Werror)

deps-scan: ## pip-audit on the locked dependencies (image scan added with T103)
	cd $(INGEST) && uv export --locked --no-dev --no-emit-project --format requirements-txt \
	  | uv run pip-audit --strict -r /dev/stdin

coverage: ## Coverage report, no threshold (pytest-cov)
	$(PYTEST) --cov=energy_ingestion --cov-branch --cov-report=term --cov-report=html:$(ROOT)/coverage/python \
	  $(INGEST)/tests $(ROOT)/tests/contract

# ---- Contracts and server ------------------------------------------------------

.PHONY: contracts-test server-test evaluation-test
contracts-test: ## Validate schemas, fixtures, and topic/identity rules
	$(PYTEST) -m "not integration and not hw" $(ROOT)/tests/contract

server-test: ## Ingestion unit tests and migration test
	$(PYTEST) -m "not integration and not hw" $(INGEST)/tests

evaluation-test: ## Evaluation scripts on fixtures with known answers (E1 plausibility)
	$(PYTEST) -m "not integration and not hw" $(ROOT)/tests/evaluation

# ---- Infrastructure (T014-T020) -------------------------------------------------

.PHONY: dev-certs infra-config-check infra-up infra-health infra-down
dev-certs: ## Create the lab CA and leaf certificates in infrastructure/secrets/
	@set -a; if [ -f $(ROOT)/.env ]; then source $(ROOT)/.env; fi; set +a; bash $(ROOT)/scripts/dev-certs.sh $(CERT_NODES)

infra-config-check: ## Validate Compose, Mosquitto, Caddy, and Grafana configuration
	@set -a; if [ -f $(ROOT)/.env ]; then source $(ROOT)/.env; fi; set +a; bash $(ROOT)/scripts/dev-certs.sh $(CERT_NODES)
	@bash $(ROOT)/infrastructure/influxdb/setup.sh --prepare
	@test -e $(ROOT)/infrastructure/secrets/notification-token || install -m 0600 /dev/null $(ROOT)/infrastructure/secrets/notification-token
	@$(COMPOSE) -f $(ROOT)/infrastructure/compose.lock.yaml config -q
	@$(COMPOSE) -f $(ROOT)/infrastructure/compose.lock.yaml config --format json | python3 -c 'import json,re,sys; c=json.load(sys.stdin); allowed={"8883","443"}; ports={str(p.get("published","")) if isinstance(p,dict) else str(p).split(":")[-1].split("/")[0] for s in c["services"].values() for p in s.get("ports",[])}; bad=ports-allowed; assert not bad and ports==allowed, f"unexpected published ports: {sorted(ports)}"; imgs={n:s.get("image","") for n,s in c["services"].items() if s.get("image")}; bad={n:i for n,i in imgs.items() if n not in {"ingestion","ingestion-secrets"} and not re.search(r"@sha256:[0-9a-f]{64}$$",i)}; assert not bad, f"unpinned service images: {bad}"; print("PASS Compose port and image pin checks")'
	@if docker info >/dev/null 2>&1; then \
	  docker run --rm --user 0 -v $(ROOT)/infrastructure/mosquitto:/mosquitto/config:ro -v $(ROOT)/infrastructure/secrets:/run/secrets:ro --entrypoint mosquitto eclipse-mosquitto:2.1.2-alpine@sha256:75d6662dee52c947dc9dd9c29f1d8d7ffef78ddaf38001caa09755681e8bbc98 --test-config -c /mosquitto/config/mosquitto.conf; \
	  DASHBOARD_HOSTNAME=$$(awk -F= '$$1=="DASHBOARD_HOSTNAME" {print $$2}' $(ROOT)/.env) docker run --rm -e DASHBOARD_HOSTNAME -v $(ROOT)/infrastructure/caddy/Caddyfile:/etc/caddy/Caddyfile:ro --entrypoint caddy caddy:2.11.9@sha256:4851e54a46b206517c574821bb5cc67f170d2156041e9fbc4c9193b45e84a75b validate --config /etc/caddy/Caddyfile; \
	else \
	  python3 -c 'from pathlib import Path; import yaml; yaml.safe_load(Path("$(ROOT)/infrastructure/compose.yaml").read_text()); yaml.safe_load(Path("$(ROOT)/infrastructure/compose.lock.yaml").read_text()); print("PASS YAML syntax checks (Docker daemon unavailable; container validators skipped)")'; \
	  python3 -c 'from pathlib import Path; p=Path("$(ROOT)/infrastructure/mosquitto/mosquitto.conf").read_text(); required=("listener 8883", "require_certificate true", "use_identity_as_username true", "allow_anonymous false", "tls_version tlsv1.2"); assert all(x in p for x in required); print("PASS Mosquitto directive checks")'; \
	  python3 -c 'from pathlib import Path; s=Path("$(ROOT)/infrastructure/caddy/Caddyfile").read_text(); assert s.count("{")==s.count("}"); assert "tls internal" in s and "reverse_proxy grafana:3000" in s; print("PASS Caddy structure checks")'; \
	fi

infra-up: infra-config-check ## Start the Compose stack
	@bash $(ROOT)/infrastructure/influxdb/setup.sh --prepare
	@test -f $(ROOT)/.env || { echo 'Copy .env.example to .env and set LAN_BIND_ADDRESS first.' >&2; exit 1; }
	@test -e $(ROOT)/infrastructure/secrets/notification-token || install -m 0600 /dev/null $(ROOT)/infrastructure/secrets/notification-token
	-$(COMPOSE) -f $(ROOT)/infrastructure/compose.lock.yaml rm -sf mosquitto-secrets ingestion-secrets grafana-secrets >/dev/null
	$(COMPOSE) -f $(ROOT)/infrastructure/compose.lock.yaml up -d --wait --wait-timeout 180 --remove-orphans influxdb
	@bash $(ROOT)/infrastructure/influxdb/setup.sh --apply
	$(COMPOSE) -f $(ROOT)/infrastructure/compose.lock.yaml up -d --build --remove-orphans

infra-health: ## Check broker, InfluxDB, Grafana, Caddy, and ingestion readiness
	@set -a; source $(ROOT)/.env; set +a; bash $(ROOT)/scripts/infra-health.sh

infra-down: ## Stop the Compose stack (volumes are kept)
	$(COMPOSE) -f $(ROOT)/infrastructure/compose.lock.yaml down --remove-orphans

# ---- Simulator and acceptance --------------------------------------------------

.PHONY: simulate acceptance-simulated test-integration test-recovery test-security evidence-export
simulate: ## Run the node simulator: make simulate SCENARIO=normal DURATION=10m
	$(UV) python -m energy_ingestion.cli.simulate --scenario $(SCENARIO) --duration $(DURATION) $(SIM_ARGS)

ACCEPTANCE_DURATION_S ?= 3600

acceptance-simulated: ## Simulated acceptance run, US1 (SC-002, SC-006); 1 h by default (needs infra-up)
	ACCEPTANCE_DURATION_S=$(ACCEPTANCE_DURATION_S) $(PYTEST) -m integration -s $(ROOT)/tests/acceptance

test-integration: ## Broker-to-dashboard integration tests (needs infra-up)
	$(PYTEST) -m integration $(ROOT)/tests/integration

test-recovery: ## Outage recovery test: make test-recovery OUTAGE=10m
	$(call planned,US1)

test-security: ## Certificate/ACL negative tests and LAN port scan
	$(call planned,US1)

evidence-export: ## Export an acceptance run: make evidence-export RUN_ID=...
	$(call planned,Phase 6)

# ---- Firmware ------------------------------------------------------------------

.PHONY: firmware-test firmware-build firmware-flash-test-fixtures
firmware-test: ## Firmware logic tests on this PC (no board): Unity + ASan/UBSan
	$(PYTEST) -m "not integration and not hw" $(ROOT)/tests/fixtures/waveforms
	IDF_PATH=$(IDF_PATH) cmake -S $(FIRMWARE)/test/host -B $(HOST_BUILD) -G Ninja -DCMAKE_BUILD_TYPE=Debug >/dev/null
	cmake --build $(HOST_BUILD)
	ctest --test-dir $(HOST_BUILD) --output-on-failure

firmware-build: ## Build the ESP32-S3 image (needs ESP-IDF 5.4)
	source $(IDF_EXPORT) >/dev/null && idf.py -C $(FIRMWARE) build

BRINGUP_APPS := stage1_board stage2_peripherals stage34_adc_logger

.PHONY: firmware-build-bringup
firmware-build-bringup: ## Compile-check the build guide stage 1-4 bring-up apps
	source $(IDF_EXPORT) >/dev/null && for app in $(BRINGUP_APPS); do \
	  idf.py -C $(FIRMWARE)/bringup/$$app build >/dev/null && echo "$$app: built"; done

firmware-flash-test-fixtures: ## On-target tests and fixture replay (board needed)
	$(call planned,T101 [HW])

# ---- Aggregate ------------------------------------------------------------------

.PHONY: test
test: lint firmware-test contracts-test server-test evaluation-test ## All fast PC gates
