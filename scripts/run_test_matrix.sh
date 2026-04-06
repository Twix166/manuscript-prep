#!/usr/bin/env bash
set -euo pipefail

python -m pytest -m unit
python -m pytest -m regression
python -m pytest -m smoke
python -m pytest -m integration

