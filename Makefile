# You can set these variables from the command line.
DJANGO = python manage.py
SETTINGS = settings_local

.PHONY: help docs test test_force_db tdd test_failed update_code update_deps update_db update_landfill full_update reindex

help:
	@echo "Please use \`make <target>' where <target> is one of"
	@echo "  docs             to builds the docs for Zamboni"
	@echo "  test             to run all the test suite"
	@echo "  test_force_db    to run all the test suite with a new database"
	@echo "  tdd              to run all the test suite, but stop on the first error"
	@echo "  test_failed      to rerun the failed tests from the previous run"
	@echo "  update_code      to update the git repository and submodules"
	@echo "  update_deps      to update the python and npm dependencies"
	@echo "  update_db        to run the database migrations"
	@echo "  full_update      to update the code, the dependencies and the database"
	@echo "  update_landfill  to load the landfill database data"
	@echo "  reindex          to reindex everything in elasticsearch, for AMO"
	@echo "Check the Makefile to know exactly what each target is doing. If you see a "
	@echo "target using something like $(SETTINGS), you can make it use another value:"
	@echo "  make SETTINGS=settings_mine docs"

docs:
	$(MAKE) -C docs html

test:
	$(DJANGO) test --settings=$(SETTINGS) --noinput --logging-clear-handlers --with-id -v 2 $(ARGS)

test_force_db:
	FORCE_DB=1 $(DJANGO) test --settings=$(SETTINGS) --noinput --logging-clear-handlers --with-id -v 2 $(ARGS)

tdd:
	$(DJANGO) test --settings=$(SETTINGS) --noinput --failfast --pdb --with-id -v 2 $(ARGS)

test_failed:
	$(DJANGO) test --settings=$(SETTINGS) --noinput --logging-clear-handlers --with-id -v 2 --failed $(ARGS)

update_code:
	git checkout master && git pull && git submodule update --init --recursive
	cd vendor && git pull && git submodule update --init && cd -

update_deps:
	pip install --no-deps --exists-action=w --download-cache=/tmp/pip-cache -r requirements/dev.txt --find-links https://pyrepo.addons.mozilla.org/ --allow-external PIL --allow-unverified PIL
	npm install

update_db:
	schematic migrations

full_update: update_code update_deps update_db

update_landfill:
	$(DJANGO) install_landfill --settings=$(SETTINGS) $(ARGS)

reindex:
	$(DJANGO) reindex --settings=$(SETTINGS) $(ARGS)
