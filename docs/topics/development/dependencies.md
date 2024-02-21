# Project Dependencies

This document describes how to add/upgrade dependencies in the project.
We use pip to manage dependencies and hashin to lock versions. We use npm to manage frontend dependencies.

## Python

### Adding Python Dependencies

We have 2 requirements files for python dependencies:

- prod.txt
- dev.txt

Prod dependencies are used by our django app in runtime.
They are strictly required to be installed in the production environment.

Dev dependencies are used by our django app in development or by tools we use for linting, testing, etc.

To ensure a standard and sane process for installing packages,
use the `make install` command to install a new package.
This will add your specified version to one of our requirements/(dev|prod).txt files and
install the package in your local container.

```bash
make install [package]==[version] --dev --prod
```

Note: This script is strict. You must specify a version, and you must specify either dev or prod.

### Upgrading Python Dependencies

TBD

## Frontend

### Adding Frontend Dependencies

We use npm to manage frontend dependencies. To add a new dependency, use the following command:

```bash
npm install [package]@[version] --save --save-dev
```

NPM is a fully featured package manager and so you can use the standard CLI.

## Updating/Installing dependencies

To update/install all dependencies, run the following command:

```bash
make update_deps
```

This will install all python and frontend dependencies. It also ensures olympia is installed locally.
By default this command will run in a docker container, but you can run it on a host by targetting the Makefile-docker

```bash
make -f Makefile-docker update_deps
```

This is used in github actions for example that do not need a full container to run.
