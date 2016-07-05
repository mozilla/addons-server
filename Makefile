.PHONY: help docs test test_es test_no_es test_force_db tdd test_failed initialize_db populate_data update_code update_deps update_db update_assets full_init full_update reindex flake8 update_docker initialize_docker shell debug
NUM_ADDONS=10
NUM_THEMES=$(NUM_ADDONS)

APP=src/olympia/

# Get the name of the Makefile's directory for the docker container base name.
mkfile_path := $(abspath $(lastword $(MAKEFILE_LIST)))
current_dir := $(notdir $(patsubst %/,%,$(dir $(mkfile_path))))

COMPOSE_PROJECT_NAME?=$(shell echo "${current_dir}" | tr -d '-' | tr -d '_')
DOCKER_NAME="${COMPOSE_PROJECT_NAME}_web_1"

UNAME_S := $(shell uname -s)

IN_DOCKER = $(wildcard /addons-server-centos7-container)

NPM_ARGS :=

ifneq ($(NPM_CONFIG_PREFIX),)
	NPM_ARGS := --prefix $(NPM_CONFIG_PREFIX)
endif

help:
	@echo "Please use 'make <target>' where <target> is one of the following commands."
	@echo "Commands that are designed be run in the container:"
	@echo "  full_init         to init the code, the dependencies and the database"
	@echo "  full_update       to update the code, the dependencies and the database"
	@echo "  initialize_db     to create a new database"
	@echo "  initialize_docker to initialize a docker image"
	@echo "  populate_data     to populate a new database"
	@echo "  reindex           to reindex everything in elasticsearch, for AMO"
	@echo "  update_deps       to update the pythondependencies"
	@echo "  update_db         to run the database migrations"
	@echo "Commands that are designed to be run in the host:"
	@echo "  debug             to connect to a running addons-server docker for debugging"
	@echo "  djshell           to connect to a running addons-server django docker shell"
	@echo "  make              to connect to a running addons-server docker and run make ARGS"
	@echo "  shell             to connect to a running addons-server docker shell"
	@echo "  tdd               to run the entire test suite, but stop on the first error"
	@echo "  test              to run the entire test suite"
	@echo "  test_es           to run the ES tests"
	@echo "  test_failed       to rerun the failed tests from the previous run"
	@echo "  test_force_db     to run the entire test suite with a new database"
	@echo "  test_no_es        to run all but the ES tests"
	@echo "  update_docker     to update a docker image"
	@echo "Commands that are designed to be run in either the container or the host:"
	@echo "  docs              to builds the documentation"
	@echo "  flake8            to run the flake8 linter"
	@echo "  update_code       to update the git repository"

	@echo "Check the Makefile to know exactly what each target is doing."

docs:
	$(MAKE) -C docs html

test:
ifneq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the host)
endif
	docker exec -t -i ${DOCKER_NAME} py.test $(APP) $(ARGS)

test_es:
ifneq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the host)
endif
	docker exec -t -i ${DOCKER_NAME} py.test -m es_tests $(APP) $(ARGS)

test_no_es:
ifneq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the host)
endif
	docker exec -t -i ${DOCKER_NAME} py.test -m "not es_tests" $(APP) $(ARGS)

test_force_db:
ifneq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the host)
endif
	docker exec -t -i ${DOCKER_NAME} py.test --create-db $(APP) $(ARGS)

tdd:
ifneq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the host)
endif
	docker exec -t -i ${DOCKER_NAME} py.test -x --pdb $(ARGS) $(APP)

test_failed:
ifneq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the host)
endif
	docker exec -t -i ${DOCKER_NAME} py.test --lf $(ARGS) $(APP)

initialize_db:
ifeq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the container)
endif
	python manage.py reset_db
	python manage.py syncdb --noinput
	python manage.py loaddata initial.json
	python manage.py import_prod_versions
	schematic --fake src/olympia/migrations/
	python manage.py createsuperuser
	python manage.py loaddata zadmin/users

populate_data:
ifeq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the container)
endif
	# reindex --wipe will force the ES mapping to be re-installed. Useful to
	# make sure the mapping is correct before adding a bunch of add-ons.
	python manage.py reindex --wipe --force --noinput
	python manage.py generate_addons --app firefox $(NUM_ADDONS)
	python manage.py generate_addons --app thunderbird $(NUM_ADDONS)
	python manage.py generate_addons --app android $(NUM_ADDONS)
	python manage.py generate_addons --app seamonkey $(NUM_ADDONS)
	python manage.py generate_themes $(NUM_THEMES)
	# Now that addons have been generated, reindex.
	python manage.py reindex --force --noinput
	# Also update category counts (denormalized field)
	python manage.py cron category_totals

update_code:
	git checkout master && git pull

install_python_dependencies:
ifeq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the container)
endif
	pip install -e .
	pip install --no-deps --exists-action=w -r requirements/dev.txt
	pip install --no-deps --exists-action=w -r requirements/docs.txt
	pip install --no-deps --exists-action=w -r requirements/prod_without_hash.txt

install_node_dependencies:
ifeq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the container)
endif
	npm install $(NPM_ARGS)

update_deps:
ifeq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the container)
endif
	$(MAKE) install_python_dependencies install_node_dependencies

update_db:
ifeq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the container)
endif
	schematic src/olympia/migrations

update_assets:
ifeq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the container)
endif
	python manage.py compress_assets
	python manage.py collectstatic --noinput

update_docker:
ifneq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the host)
endif
	docker exec -t -i ${DOCKER_NAME} make update_docker_inner

update_docker_inner:
ifeq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the container)
endif
	$(MAKE) update_deps update_db update_assets

full_init:
ifeq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the container)
endif
	$(MAKE) update_deps initialize_db populate_data update_assets

full_update:
ifeq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the container)
endif
	$(MAKE) update_code update_deps update_db update_assets

reindex:
ifeq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the container)
endif
	python manage.py reindex $(ARGS)

# Guessing that people could have flake8 locally and it could work in
# both the container and in the host.
flake8:
	flake8 src/ --ignore=F999

initialize_docker:
ifneq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the host)
endif
	docker exec -t -i ${DOCKER_NAME} make initialize_docker_inner

initialize_docker_inner:
ifeq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the container)
endif
	$(MAKE) initialize_db update_assets populate_data

debug:
ifneq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the host)
endif
	docker exec -t -i ${DOCKER_NAME} supervisorctl fg olympia

shell:
ifneq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the host)
endif
	docker exec -t -i ${DOCKER_NAME} bash

djshell:
ifneq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the host)
endif
	docker exec -t -i ${DOCKER_NAME} ./manage.py shell

# Run a make command in the container
make:
ifeq ($(IN_DOCKER),)
	$(warning Command is designed to be run in the host)
endif
	docker exec -t -i ${DOCKER_NAME} make $(ARGS)
