IN_DOCKER = $(wildcard /addons-server-docker-container)

ifneq ($(IN_DOCKER),)
	SUB_MAKEFILE = Makefile-docker
else
	SUB_MAKEFILE = Makefile-os
endif

include $(SUB_MAKEFILE)


help:
	@echo "Please use 'make <target>' where <target> is one of the following commands.\n"
	@$(MAKE) help_submake --no-print-directory
	@echo "\nCheck the Makefile to know exactly what each target is doing."

# You probably want to put new commands in Makefile-docker rather than here -
# unless they operate on multiple containers or are host-os specific, then
# Makefile-os instead.
