.PHONY: help docs test test_force_db tdd test_failed initialize_db populate_data update_code update_deps update_db update_assets full_init full_update reindex flake8
NUM_ADDONS=10
NUM_THEMES=$(NUM_ADDONS)

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
	@echo "  update_db         to run the database migrations"
	@echo "  full_init         to init the code, the dependencies and the database"
	@echo "  full_update       to update the code, the dependencies and the database"
	@echo "  reindex           to reindex everything in elasticsearch, for AMO"
	@echo "  flake8            to run the flake8 linter"
	@echo "Check the Makefile  to know exactly what each target is doing. If you see a "

docs:
	$(MAKE) -C docs html

test:
	REUSE_DB=1 python manage.py test --with-blockage --noinput --logging-clear-handlers --with-id -v 2 $(ARGS)

test_force_db:
	python manage.py test --with-blockage --noinput --logging-clear-handlers --with-id -v 2 $(ARGS)

tdd:
	REUSE_DB=1 python manage.py test --with-blockage --noinput --failfast --pdb --with-id -v 2 $(ARGS)

test_failed:
	REUSE_DB=1 python manage.py test --with-blockage --noinput --logging-clear-handlers --with-id -v 2 --failed $(ARGS)

initialize_db:
	python manage.py reset_db
	python manage.py syncdb --noinput
	python manage.py loaddata initial.json
	python manage.py import_prod_versions
	schematic --fake migrations/
	python manage.py createsuperuser

populate_data:
	python manage.py generate_addons --app firefox $(NUM_ADDONS)
	python manage.py generate_addons --app thunderbird $(NUM_ADDONS)
	python manage.py generate_addons --app android $(NUM_ADDONS)
	python manage.py generate_addons --app seamonkey $(NUM_ADDONS)
	python manage.py generate_themes $(NUM_THEMES)
	python manage.py reindex --wipe --force

update_code:
	git checkout master && git pull

update_deps:
	pip install --no-deps --exists-action=w --download-cache=/tmp/pip-cache -r requirements/dev.txt --find-links https://pyrepo.addons.mozilla.org/
	npm install

update_db:
	schematic migrations

update_assets:
	python manage.py compress_assets
	python manage.py collectstatic --noinput

full_init: update_deps initialize_db populate_data update_assets

full_update: update_code update_deps update_db update_assets

reindex:
	python manage.py reindex $(ARGS)

flake8:
	flake8 --ignore=E265 --exclude=services,wsgi,docs,node_modules,build*.py .
