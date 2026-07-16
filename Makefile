# Add-a-model UX (ADDON checklist). Target: <1hr wall time excl. weight download.
# If any step needs manual editing beyond models.yaml, that step is a bug.

RUNS ?= runs/legA-full.jsonl
BASE_URL ?= https://PENDING.deploy

.PHONY: bench pricing payskill verify-registry help

help:
	@echo "make bench MODEL=<id>   # pricing subset of the matrix for one model (on box)"
	@echo "make pricing            # harness JSONL -> derived prices in models.yaml"
	@echo "make payskill           # regenerate pay.sh listing (P5: then sync+validate+PR)"
	@echo "make verify-registry    # sanity: registry loads + hash stable"

bench:
	@test -n "$(MODEL)" || (echo "MODEL=<id> required"; exit 1)
	uv run python -m harness.pricing_bench $(MODEL)

pricing:
	uv run python report/pricing.py $(RUNS)

payskill:
	uv run python payskill/generate_listing.py $(BASE_URL)

verify-registry:
	uv run python -c "from server import registry; r=registry.load(); print('models:', sorted(r)); print('registry_hash:', registry.registry_hash(r).hex())"
