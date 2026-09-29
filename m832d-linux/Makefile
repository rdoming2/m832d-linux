.PHONY: ppd check install uninstall clean

PPD_BUILD ?= build/ppd

ppd:
	mkdir -p "$(PPD_BUILD)"
	ppdc -d "$(PPD_BUILD)" cups/drv/m832d.drv

check: ppd
	PYTHONPATH=src python -m unittest discover -v

install: ppd
	./scripts/install.sh

uninstall:
	./scripts/uninstall.sh

clean:
	rm -rf "$(PPD_BUILD)"
