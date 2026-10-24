# Add-a-model workflow. Target: <1hr wall time excluding weight download.
# If any step needs manual editing beyond models.yaml, that step is a bug.

RUNS ?= runs/legA-full.jsonl
BASE_URL ?= https://vinfer.mcgee.cat
PAID_URL ?= https://pay.example.invalid
PAY_NETWORK ?= localnet
PAY_MAX_REQUEST_USD ?= 0.50
OPERATOR ?= catmcgee

.PHONY: bench pricing pay-runtime pay-openapi payskill pay-sandbox-test verify-registry curate report generated check-generated test test-python test-web solana-test check help

help:
	@echo "make bench MODEL=<id>   # pricing subset of the matrix for one model (on box)"
	@echo "make pricing [MODEL=<id>] # model pricing run (or RUNS) -> models.yaml"
	@echo "make pay-runtime        # models.yaml -> pay gateway inference.yaml"
	@echo "make pay-openapi        # API routes -> pay gateway OpenAPI document"
	@echo "make pay-sandbox-test   # real local x402-upto challenge/payment/proxy cycle"
	@echo "make payskill           # runtime YAML -> provider sync -> catalog validation"
	@echo "make verify-registry    # sanity: registry loads + hash stable"
	@echo "make report             # curate raw runs + regenerate frontend measurements"
	@echo "make test               # Python, browser, and Anchor tests"
	@echo "make check              # deterministic Python/web/generated-data quality gate"
	@echo "make solana-test        # Anchor integration tests on a local validator"

bench:
	@test -n "$(MODEL)" || (echo "MODEL=<id> required"; exit 1)
	uv run python -m harness.pricing_bench $(MODEL)

pricing:
	uv run python report/pricing.py $(if $(MODEL),runs/pricing/$(MODEL).jsonl,$(RUNS))

pay-runtime:
	uv run python payskill/generate_runtime.py \
		--upstream $(BASE_URL) \
		--network $(PAY_NETWORK) \
		--max-request-usd $(PAY_MAX_REQUEST_USD)

pay-openapi:
	uv run python -m payskill.generate_listing \
		--service-url $(PAID_URL) \
		--openapi-only

payskill:
	uv run python payskill/generate_listing.py \
		--origin-url $(BASE_URL) \
		--service-url $(PAID_URL) \
		--operator $(OPERATOR) \
		--network $(PAY_NETWORK) \
		--max-request-usd $(PAY_MAX_REQUEST_USD)

pay-sandbox-test:
	uv run python tests/pay_gateway_e2e.py

verify-registry:
	uv run python -c "from server import registry; r=registry.load(); print('models:', sorted(r)); print('registry_hash:', registry.registry_hash(r).hex())"

curate:
	uv run python report/curate_runs.py

report: curate
	uv run python report/measurements_json.py

generated: pay-runtime pay-openapi
	uv run python report/measurements_json.py

check-generated:
	@tmp=$$(mktemp -d); trap 'rm -rf "$$tmp"' EXIT; \
	cp web/public/measurements.json "$$tmp/measurements.json"; \
	cp payskill/inference.yaml "$$tmp/inference.yaml"; \
	cp payskill/openapi.json "$$tmp/openapi.json"; \
	$(MAKE) generated >/dev/null; \
	cmp "$$tmp/measurements.json" web/public/measurements.json; \
	cmp "$$tmp/inference.yaml" payskill/inference.yaml; \
	cmp "$$tmp/openapi.json" payskill/openapi.json

test: test-python test-web solana-test

test-python:
	uv run python -m unittest discover -s tests -v

test-web:
	npm --prefix web run test:e2e

check: test-python verify-registry check-generated
	git diff --check
	npm --prefix web run lint
	npm --prefix web run build
	npm --prefix web run test:e2e
	npm --prefix solana run lint

solana-test:
	cd solana && anchor test --validator legacy
