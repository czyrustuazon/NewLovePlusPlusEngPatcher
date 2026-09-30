# NLPP a/b Azahar workflow.
# From the repo root:
#   .\ab_test\make.ps1 deploy-a
#   make -C ab_test deploy-a
#
# GNU Make is optional (MSYS2: pacman -S make).

MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
RUN := powershell -NoProfile -ExecutionPolicy Bypass -File "$(MAKEFILE_DIR)make.ps1"

.DEFAULT_GOAL := help

.PHONY: help
help:
	@$(RUN) help

%:
	@$(RUN) $@
