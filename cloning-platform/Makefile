.PHONY: install lint type-check test clean

install:
	pip install -r requirements-dev.txt

lint:
	ruff check src/ tests/
	black --check src/ tests/

type-check:
	mypy src/

test:
	pytest tests/unit/ -v

test-all:
	pytest tests/ -v

coverage:
	pytest tests/unit/ --cov=src --cov-report=html --cov-fail-under=80

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .coverage htmlcov/ .mypy_cache/ .pytest_cache/ .ruff_cache/
