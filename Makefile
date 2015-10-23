.PHONY: help docs test test_es test_no_es test_force_db tdd test_failed initialize_db populate_data update_code update_deps update_db update_assets full_init full_update reindex flake8 update_docker initialize_docker shell debug
NUM_ADDONS=10
NUM_THEMES=$(NUM_ADDONS)

UNAME_S := $(shell uname -s)

help:
	@echo "Please use 'make <target>' where <target> is one of"
	@echo "  shell             to connect to a running olympia docker shell"
	@echo "  debug             to connect to a running olympia docker for debugging"
	@echo "  make              to connect to a running olympia docker and run make ARGS"
	@echo "  docs              to builds the docs for Zamboni"
	@echo "  test              to run all the test suite"
	@echo "  test_force_db     to run all the test suite with a new database"
	@echo "  tdd               to run all the test suite, but stop on the first error"
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
	py.test $(ARGS)

test_es:
	py.test -m es_tests $(ARGS)

test_no_es:
	py.test -m "not es_tests" $(ARGS)

test_force_db:
	py.test --create-db $(ARGS)

tdd:
	py.test -x --pdb $(ARGS)

test_failed:
	py.test --lf $(ARGS)

initialize_db:
	python manage.py reset_db
	python manage.py syncdb --noinput
	python manage.py loaddata initial.json
	python manage.py import_prod_versions
	schematic --fake migrations/
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

update_deps:
	pip install --no-deps --exists-action=w -r requirements/dev.txt --find-links https://pyrepo.addons.mozilla.org/wheelhouse/ --find-links https://pyrepo.addons.mozilla.org/ --no-index

update_db:
	schematic migrations

update_assets:
	python manage.py compress_assets
	python manage.py collectstatic --noinput

update_docker:
	docker exec -t -i olympia_web_1 make update_docker_inner

update_docker_inner: update_db update_assets

full_init: update_deps initialize_db populate_data update_assets

full_update: update_code update_deps update_db update_assets

reindex:
	python manage.py reindex $(ARGS)

flake8:
	flake8 --ignore=E265,E266 --exclude=services,wsgi,docs,node_modules,.npm,build*.py .

initialize_docker:
	docker exec -t -i olympia_web_1 make initialize_docker_inner

initialize_docker_inner: initialize_db update_assets
	$(MAKE) populate_data

debug:
	docker exec -t -i olympia_web_1 supervisorctl fg olympia

shell:
	docker exec -t -i olympia_web_1 bash

djshell:
	docker exec -t -i olympia_web_1 ./manage.py shell

# Run a make command in docker.
make:
	docker exec -t -i olympia_web_1 make $(ARGS)
