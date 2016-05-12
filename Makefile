.PHONY: help docs test test_es test_no_es test_force_db tdd test_failed initialize_db populate_data update_code update_deps update_db update_assets full_init full_update reindex flake8 update_docker initialize_docker shell debug
NUM_ADDONS=10
NUM_THEMES=$(NUM_ADDONS)

# Get the name of the Makefile's directory for the docker container base name.
mkfile_path := $(abspath $(lastword $(MAKEFILE_LIST)))
current_dir := $(notdir $(patsubst %/,%,$(dir $(mkfile_path))))

COMPOSE_PROJECT_NAME?=$(shell echo "${current_dir}" | tr -d '-' | tr -d '_')
DOCKER_NAME="${COMPOSE_PROJECT_NAME}_web_1"

UNAME_S := $(shell uname -s)

help:
	@echo "Please use 'make <target>' where <target> is one of"
	@echo "  shell             to connect to a running addons-server docker shell"
	@echo "  debug             to connect to a running addons-server docker for debugging"
	@echo "  make              to connect to a running addons-server docker and run make ARGS"
	@echo "  docs              to builds the docs for Zamboni"
	@echo "  test              to run the entire test suite"
	@echo "  test_force_db     to run the entire test suite with a new database"
	@echo "  tdd               to run the entire test suite, but stop on the first error"
	@echo "  test_failed       to rerun the failed tests from the previous run"
	@echo "  initialize_db     to create a new database"
	@echo "  populate_data     to populate a new database"
	@echo "  update_code       to update the git repository"
	@echo "  update_deps       to update the pythondependencies"
	@echo "  update_db         to run the database migrations"
	@echo "  initialize_docker to initialize a docker image"
	@echo "  update_docker     to update a docker image"
	@echo "  full_init         to init the code, the dependencies and the database"
	@echo "  full_update       to update the code, the dependencies and the database"
	@echo "  reindex           to reindex everything in elasticsearch, for AMO"
	@echo "  flake8            to run the flake8 linter"
	@echo "Check the Makefile to know exactly what each target is doing. If you see a "
	@echo "target using something like $$(SETTINGS), you can make it use another value:"
	@echo "  make SETTINGS=settings_mine docs"

docs:
	$(MAKE) -C docs html

test:
	docker exec -t -i ${DOCKER_NAME} py.test $(ARGS)

test_es:
	docker exec -t -i ${DOCKER_NAME} py.test -m es_tests $(ARGS)

test_no_es:
	docker exec -t -i ${DOCKER_NAME} py.test -m "not es_tests" $(ARGS)

test_force_db:
	docker exec -t -i ${DOCKER_NAME} py.test --create-db $(ARGS)

tdd:
	docker exec -t -i ${DOCKER_NAME} py.test -x --pdb $(ARGS)

test_failed:
	docker exec -t -i ${DOCKER_NAME} py.test --lf $(ARGS)

initialize_db:
	python manage.py reset_db
	python manage.py syncdb --noinput
	python manage.py loaddata initial.json
	python manage.py import_prod_versions
	schematic --fake src/olympia/migrations/
	python manage.py createsuperuser
	python manage.py loaddata zadmin/users

populate_data:
	python manage.py generate_addons --app firefox $(NUM_ADDONS)
	python manage.py generate_addons --app thunderbird $(NUM_ADDONS)
	python manage.py generate_addons --app android $(NUM_ADDONS)
	python manage.py generate_addons --app seamonkey $(NUM_ADDONS)
	python manage.py generate_themes $(NUM_THEMES)
	python manage.py reindex --wipe --force --noinput

update_code:
	git checkout master && git pull

install_python_dependencies:
	pip install -e .
	pip install --no-deps --exists-action=w -r requirements/docker.txt
	pip install --no-deps --exists-action=w -r requirements/prod_without_hash.txt

install_node_dependencies:
	npm install

update_deps: install_python_dependencies install_node_dependencies

update_db:
	schematic src/olympia/migrations

update_assets:
	python manage.py compress_assets
	python manage.py collectstatic --noinput

update_docker:
	docker exec -t -i ${DOCKER_NAME} make update_docker_inner

update_docker_inner: update_db update_assets

full_init: update_deps initialize_db populate_data update_assets

full_update: update_code update_deps update_db update_assets

reindex:
	python manage.py reindex $(ARGS)

flake8:
	flake8 src/

initialize_docker:
	docker exec -t -i ${DOCKER_NAME} make initialize_docker_inner

initialize_docker_inner: initialize_db update_assets
	$(MAKE) populate_data

debug:
	docker exec -t -i ${DOCKER_NAME} supervisorctl fg olympia

shell:
	docker exec -t -i ${DOCKER_NAME} bash

djshell:
	docker exec -t -i ${DOCKER_NAME} ./manage.py shell

# Run a make command in docker.
make:
	docker exec -t -i ${DOCKER_NAME} make $(ARGS)
