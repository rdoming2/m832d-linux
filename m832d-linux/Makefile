.PHONY: ppd check

PPD_BUILD ?= build/ppd

ppd:
	mkdir -p "$(PPD_BUILD)"
	ppdc -d "$(PPD_BUILD)" cups/drv/m832d.drv

check: ppd
	PYTHONPATH=src python -m unittest discover -v
