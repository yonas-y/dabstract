#!/usr/bin/env bash
pip3 install -r requirements.txt
make clean
rm -Rf source/docstring
#sphinx-apidoc -f -o source/docstring/dataprocessor ../dabstract/dataprocessor
#sphinx-apidoc -f -o source/docstring/dataset ../dabstract/dataset
#sphinx-apidoc -f -o source/docstring ../dabstract
make html