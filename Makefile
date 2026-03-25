PYTHON ?= /usr/bin/python3
num ?= 5

.PHONY: help socket_update socket_sug

help:
	@echo "Available targets:"
	@echo "  make help                 Show this help message"
	@echo "  make socket_sug [num=3]   Generate recommendations and charts"

socket_update:
	$(PYTHON) /home/lhy/workspace/sockets/scripts/socket_update.py

socket_sug: socket_update
	$(PYTHON) /home/lhy/workspace/sockets/scripts/socket_recommend.py --num $(num)
