#!/usr/bin/env python3
"""
Setup script for Repo2Run.
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="repo2run",
    version="0.1.0",
    author="Repo2Run Contributors",
    author_email="example@example.com",
    description="A tool to configure and run repositories with automated dependency management",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/repo2run",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
    install_requires=[
        "tomli>=2.0.0",
        "pyyaml>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "repo2run=repo2run.main:main",
            "repo2run-extract=repo2run.tools.extract_requirements:main",
            "repo2run-install=repo2run.tools.install_package:main",
            "repo2run-test=repo2run.tools.run_tests:main",
        ],
    },
) 