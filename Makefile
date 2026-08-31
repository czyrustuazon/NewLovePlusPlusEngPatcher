# NLPP a/b Azahar workflow — root shim → ab_test/make.ps1
# Requires: GNU Make (MSYS2: pacman -S make) OR run .\make.ps1 <target> directly.
#
#   make              # same as make help
#   make deploy-a
#   .\make.ps1 deploy-a   # without GNU Make

RUN := powershell -NoProfile -ExecutionPolicy Bypass -File "make.ps1"

.PHONY: help paths build-azahar instances seed-a seed-b \
	deploy-a deploy-b deploy restore-a restore-b restore \
	launch-a launch-b all-a all-b

.DEFAULT_GOAL := help

help paths build-azahar instances seed-a seed-b \
deploy-a deploy-b deploy restore-a restore-b restore \
launch-a launch-b all-a all-b:
	@$(RUN) $@
