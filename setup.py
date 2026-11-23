"""Builds the optional C core (lifeinlife/_core.c). Everything else is in pyproject.toml.

optional=True: with no C compiler the install still works, using the numpy fallback.
From a clone, build it in place with:  python setup.py build_ext --inplace
"""
from setuptools import Extension, setup

setup(ext_modules=[Extension("lifeinlife._core", ["lifeinlife/_core.c"], optional=True)])
