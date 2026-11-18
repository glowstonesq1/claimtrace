.PHONY: dev web test lint typecheck check e2e eval serve docker clean lock audit

PY ?= .venv/bin/python

dev:            ## one-command dev setup (offline after first install)
	python3 -m venv .venv && .venv/bin/pip install -q -e '.[dev]'
	cd apps/web && npm ci --no-audit --no-fund && npm run build

web:
	cd apps/web && npm run build

serve:
	.venv/bin/claimtrace serve

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check packages apps tests

typecheck:
	.venv/bin/mypy
	cd apps/web && npm run typecheck

check:          ## ruff + mypy + pytest (what CI's python job gates on)
	.venv/bin/ruff check packages apps tests
	.venv/bin/mypy
	.venv/bin/pytest -q

e2e:            ## needs a running server on :8765 and Playwright
	cd apps/web && BASE=http://127.0.0.1:8765 node e2e/smoke.mjs

eval:
	.venv/bin/claimtrace eval run --suite core --model rules

docker:
	docker compose up --build

clean:
	rm -rf data apps/api/static apps/web/node_modules .pytest_cache .ruff_cache .mypy_cache
