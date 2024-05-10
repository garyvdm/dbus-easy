.PHONY: lint check format test docker-test clean publish docs livedocs all
.DEFAULT_GOAL := all

source_dirs = dbus_ezy test examples

lint:
	python3 -m ruff check $(source_dirs)

check: lint
	python3 -m ruff format --check $(source_dirs)

format:
	python3 -m ruff format $(source_dirs)

test:
	for py in python3.8 python3.9 python3.10 python3.11 ; do \
		if hash $${py}; then \
			PYTHONPATH=/usr/lib/$${py}/site-packages dbus-run-session $${py} -m pytest -sv --cov=dbus_ezy || exit 1 ; \
		fi \
	done \

docker-test:
	docker build -t dbus-ezy-test .
	docker run -it dbus-ezy-test

clean:
	rm -rf dist dbus_ezy.egg-info build docs/_build
	rm -rf `find -type d -name __pycache__`

publish:
	python3 python3 -m build
	python3 -m twine upload --repository-url https://upload.pypi.org/legacy/ dist/*

docs:
	sphinx-build docs docs/_build/html

livedocs:
	sphinx-autobuild docs docs/_build/html --watch dbus_ezy

all: format lint test
