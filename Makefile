# You can set these variables from the command line.
DJANGO = python manage.py
SETTINGS = settings_local

.PHONY: help docs test test_force_db tdd test_failed update update_landfill reindex reindex_mkt

help:
	@echo "Please use \`make <target>' where <target> is one of"
	@echo "  docs             to builds the docs for Zamboni"
	@echo "  test             to run all the test suite"
	@echo "  test_force_db    to run all the test suite with a new database"
	@echo "  tdd              to run all the test suite, but stop on the first error"
	@echo "  test_failed      to rerun the failed tests from the previous run"
	@echo "  update           to run a full update (git, pip, schematic, landfill)"
	@echo "  update_mkt       to run a full update of zamboni, plus any Commonplace projects"
	@echo "  reindex          to reindex everything in elasticsearch, for AMO"
	@echo "  reindex_mkt      to reindex everything in elasticsearch, for marketplace"
	@echo "Check the Makefile to know exactly what each target is doing. If you see a "
	@echo "target using something like $(SETTINGS), you can make it use another value:"
	@echo "  make SETTINGS=settings_mkt docs"

docs:
	$(MAKE) -C docs html

test:
	$(DJANGO) test --settings=$(SETTINGS) --noinput --logging-clear-handlers --with-id $(ARGS)

test_force_db:
	FORCE_DB=1 $(DJANGO) test --settings=$(SETTINGS) --noinput --logging-clear-handlers --with-id $(ARGS)

tdd:
	$(DJANGO) test --settings=$(SETTINGS) --noinput --failfast --pdb --with-id $(ARGS)

test_failed:
	$(DJANGO) test --settings=$(SETTINGS) --noinput --logging-clear-handlers --with-id --failed $(ARGS)

update:
	git checkout master && git pull && git submodule update --init --recursive
	pushd vendor && git pull && git submodule update --init && popd
	pip install --no-deps --exists-action=w --download-cache=/tmp/pip-cache -r requirements/dev.txt --find-links https://pyrepo.addons.mozilla.org/ --allow-external PIL --allow-unverified PIL
	schematic migrations
	npm install

update_mkt: update
	commonplace fiddle

update_landfill: update
	$(DJANGO) install_landfill --settings=$(SETTINGS) $(ARGS)

reindex:
	$(DJANGO) reindex --settings=$(SETTINGS) $(ARGS)

reindex_mkt:
	$(DJANGO) reindex_mkt --settings=$(SETTINGS) $(ARGS)
