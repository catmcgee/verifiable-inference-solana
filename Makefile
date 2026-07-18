# Add-a-model workflow. Target: <1hr wall time excluding weight download.
# If any step needs manual editing beyond models.yaml, that step is a bug.

RUNS ?= runs/legA-full.jsonl
BASE_URL ?= https://verified-inference.213.239.141.40.sslip.io
PAID_URL ?= https://pay.example.invalid
PAY_NETWORK ?= localnet
PAY_MAX_REQUEST_USD ?= 0.50
OPERATOR ?= catmcgee

.PHONY: bench pricing pay-runtime payskill pay-sandbox-test verify-registry migrate-jsonl curate report test check solana-test help

help:
	@echo "make bench MODEL=<id>   # pricing subset of the matrix for one model (on box)"
	@echo "make pricing [MODEL=<id>] # model pricing run (or RUNS) -> models.yaml"
	@echo "make pay-runtime        # models.yaml -> pay gateway inference.yaml"
	@echo "make pay-sandbox-test   # real local x402-upto challenge/payment/proxy cycle"
	@echo "make payskill           # runtime YAML -> provider sync -> catalog validation"
	@echo "make verify-registry    # sanity: registry loads + hash stable"
	@echo "make migrate-jsonl      # fill legacy empty quant values from models.yaml"
	@echo "make report             # curate raw runs + regenerate JSON/HTML reports"
	@echo "make test               # Python policy, parser, harness, and x402 tests"
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

migrate-jsonl:
	uv run python harness/migrate_quant.py

curate:
	uv run python report/curate_runs.py

report: curate
	uv run python report/measurements_json.py
	uv run python report/generate.py

test:
	uv run python -m unittest discover -s tests -v

check: test verify-registry
	uv run python report/measurements_json.py
	git diff --check
	git diff --exit-code -- web/public/measurements.json
	npm --prefix web run lint
	npm --prefix web run build
	npm --prefix solana run lint

solana-test:
	cd solana && anchor test
