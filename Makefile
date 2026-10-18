.PHONY: run test
run:
	python3 -m duckscale
test:
	python3 -m unittest discover -s tests -v

.PHONY: install
install:
	python3 scripts/install.py
