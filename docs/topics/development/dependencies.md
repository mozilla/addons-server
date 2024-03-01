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

> If you add just the package name the script will automatically get the latest version for you.

```bash
hashin -r <requirements file> <dependency>
```

This will add hashes and sort the requirements for you adding comments to
show any package dependencies.

When it's run check the diff and make edits to fix any issues before
submitting a PR with the additions.

### Upgrading Python Dependencies

We mostly rely on dependabot for this. TBD Add more details.

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

> Note: If you are adding a new dependency, make sure to update static assets imported from the new versions.

```bash
make update_assets
```
