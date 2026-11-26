# On Windows without make, run the `uv run ...` command shown for each target.
UV ?= uv

.PHONY: setup lint format test check corpus corridor collect-trust-stomp \
        collect-trust-kafka collect-darwin-kafka compact health data train eval

setup:            ## Install pinned dependencies from uv.lock
	$(UV) sync --locked

lint:
	$(UV) run ruff check src tests
	$(UV) run ruff format --check src tests

format:
	$(UV) run ruff format src tests
	$(UV) run ruff check --fix src tests

test:
	$(UV) run pytest

check: lint test

# --- Reference data -----------------------------------------------------------
corpus:           ## Download CORPUS (needs NR credentials in .env)
	$(UV) run rdp reference download-corpus

corridor:         ## Resolve config/corridor.yaml against CORPUS
	$(UV) run rdp corridor resolve

# --- Collectors (normally run by systemd, see deploy/) -----------------------
FILTER ?= all
collect-trust-stomp:
	$(UV) run rdp collect --source nr-stomp --feed trust --filter $(FILTER)

collect-trust-kafka:
	$(UV) run rdp collect --source rdm-kafka --feed trust --filter $(FILTER)

collect-darwin-kafka:
	$(UV) run rdp collect --source rdm-kafka --feed darwin --filter $(FILTER)

DATE ?=
compact:          ## Merge and deduplicate one UTC day of TRUST captures: make compact DATE=2026-11-27
	$(UV) run rdp compact trust --date $(DATE)

health:
	$(UV) run rdp health

# --- Pipeline stages (not implemented yet) -----------------------------------
data train eval:
	@echo "'make $@' is not implemented yet (Phase 1, later steps)." && exit 1
