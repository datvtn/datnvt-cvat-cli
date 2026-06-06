#!/bin/bash
rm -rf dist/ build/ datnvt_cvat_cli.egg-info/
python -m build &&
python -m twine upload dist/*
