.PHONY: help docs test test_es test_no_es test_force_db tdd test_failed initialize_db populate_data update_deps update_db update_assets initialize update reindex flake8 shell debug

IN_DOCKER = $(wildcard /addons-server-centos7-container)

ifneq ($(IN_DOCKER),)
	SUB_MAKEFILE = Makefile-docker
else
	SUB_MAKEFILE = Makefile-os
endif

include $(SUB_MAKEFILE)

help:
	@echo "Please use 'make <target>' where <target> is one of the following commands."
	@echo "Commands that are designed to be run in either the container or the host:"
	@echo "  docs              to builds the documentation"
	@echo "  flake8            to run the flake8 linter"
	@$(MAKE) help_submake --no-print-directory

	@echo "Check the Makefile to know exactly what each target is doing."

docs:
	$(MAKE) -C docs html

flake8:
	flake8 src/ services/
