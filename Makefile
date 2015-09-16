.PHONY: help docs test test_es test_no_es test_force_db tdd test_failed initialize_db populate_data update_code update_deps update_db update_assets full_init full_update reindex flake8 update_docker initialize_docker update_npm_deps
NUM_ADDONS=10
NUM_THEMES=$(NUM_ADDONS)

UNAME_S := $(shell uname -s)

# If you're using docker and docker-compose, you can use this Makefile to run
# commands in your docker images by setting the DOCKER_PREFIX environment variable
# to: DOCKER_PREFIX="docker-compose run --rm web"

help:
	@echo "Please use 'make <target>' where <target> is one of"
	@echo "  docs              to builds the docs for Zamboni"
	@echo "  test              to run all the test suite"
	@echo "  test_force_db     to run all the test suite with a new database"
	@echo "  tdd               to run all the test suite, but stop on the first error"
	@echo "  test_failed       to rerun the failed tests from the previous run"
	@echo "  initialize_db     to create a new database"
	@echo "  populate_data     to populate a new database"
	@echo "  update_code       to update the git repository"
	@echo "  update_deps       to update the python and npm dependencies"
	@echo "  update_npm_deps   to update only the npm dependencies"
	@echo "  update_db         to run the database migrations"
	@echo "  initialize_docker to initialize a docker image"
	@echo "  update_docker     to update a docker image"
	@echo "  full_init         to init the code, the dependencies and the database"
	@echo "  full_update       to update the code, the dependencies and the database"
	@echo "  reindex           to reindex everything in elasticsearch, for AMO"
	@echo "  flake8            to run the flake8 linter"
	@echo "Check the Makefile  to know exactly what each target is doing. If you see a "

docs:
	$(DOCKER_PREFIX) $(MAKE) -C docs html

test:
	$(DOCKER_PREFIX) py.test $(ARGS)

test_es:
	$(DOCKER_PREFIX) py.test -m es_tests $(ARGS)

test_no_es:
	$(DOCKER_PREFIX) py.test -m "not es_tests" $(ARGS)

test_force_db:
	$(DOCKER_PREFIX) py.test --create-db $(ARGS)

tdd:
	$(DOCKER_PREFIX) py.test -x --pdb $(ARGS)

test_failed:
	$(DOCKER_PREFIX) py.test --lf $(ARGS)

HIGHEST_MIGRATION = $$(cd migrations; \
		       ls | sort -rn | sed -n 's/^\([0-9]\+\).*/\1/p' | head -1)

initialize_db:
	$(DOCKER_PREFIX) python manage.py reset_db
	$(DOCKER_PREFIX) python manage.py syncdb --noinput
	$(DOCKER_PREFIX) python manage.py loaddata initial.json
	$(DOCKER_PREFIX) python manage.py import_prod_versions
	$(DOCKER_PREFIX) schematic -u $(HIGHEST_MIGRATION) migrations
	$(DOCKER_PREFIX) python manage.py createsuperuser
	$(DOCKER_PREFIX) python manage.py loaddata zadmin/users

populate_data:
	$(DOCKER_PREFIX) python manage.py generate_addons --app firefox $(NUM_ADDONS)
	$(DOCKER_PREFIX) python manage.py generate_addons --app thunderbird $(NUM_ADDONS)
	$(DOCKER_PREFIX) python manage.py generate_addons --app android $(NUM_ADDONS)
	$(DOCKER_PREFIX) python manage.py generate_addons --app seamonkey $(NUM_ADDONS)
	$(DOCKER_PREFIX) python manage.py generate_themes $(NUM_THEMES)
	$(DOCKER_PREFIX) python manage.py reindex --wipe --force

update_code:
	$(DOCKER_PREFIX) git checkout master && git pull

update_deps: update_npm_deps
	$(DOCKER_PREFIX) pip install --no-deps --exists-action=w -r requirements/dev.txt --find-links https://pyrepo.addons.mozilla.org/wheelhouse/ --find-links https://pyrepo.addons.mozilla.org/ --no-index

update_npm_deps:
	$(DOCKER_PREFIX) npm install

update_db:
	$(DOCKER_PREFIX) schematic migrations

update_assets: update_npm_deps
	$(DOCKER_PREFIX) python manage.py compress_assets
	$(DOCKER_PREFIX) python manage.py collectstatic --noinput

initialize_docker: initialize_db update_assets
	$(MAKE) populate_data

update_docker: update_db update_assets

full_init: update_deps initialize_db populate_data update_assets

full_update: update_code update_deps update_db update_assets

reindex:
	$(DOCKER_PREFIX) python manage.py reindex $(ARGS)

flake8:
	$(DOCKER_PREFIX) flake8 --ignore=E265,E266 --exclude=services,wsgi,docs,node_modules,build*.py .
