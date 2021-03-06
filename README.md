d.abstract: dataset and pre-processing abstraction
==================================================

[![Build Status](https://travis-ci.org/KULeuvenADVISE/dabstract.svg?branch=master)](https://travis-ci.org/KULeuvenADVISE/dabstract)
[![Coverage Status](https://coveralls.io/repos/github/KULeuvenADVISE/dabstract/badge.svg?branch=master)](https://coveralls.io/github/KULeuvenADVISE/dabstract?branch=master)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ambv/black)
[![Documentation Status](https://readthedocs.org/projects/dabstract/badge/?version=latest)](https://dabstract.readthedocs.io/en/latest/?badge=latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/KULeuvenADVISE/dabstract/blob/master/LICENSE)

This is a -lightweight- library for defining and processing data(sets). The goals of the library are to 
    a) uniformize dataset classes,
    b) speed up experiments where the data does not fit into memory, 
    c) offer a general way of processing data independent of the data source, 
    d) seamlessly combine different datasets.
     
The reader is advised to first go through EXAMPLES/introduction_notebook/Readme1/2/3_* and then check the EXAMPLE implementation.
For more information on each function check the docstrings or https://dabstract.readthedocs.io/. 

## Install instructions
1) clone to a folder of choice (should be easily accessible, e.g. among other utilities)
2) go to folder in terminal
3) "pip install --editable ."

The --editable flag makes sure that the package uses the files you used for installing as source, such that you can adjust and push updates to this repository when you have a new feature or for a bug fix.

