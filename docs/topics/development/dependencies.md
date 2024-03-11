# Project Dependencies

This document describes how to add/upgrade dependencies in the project.
We use pip to manage dependencies and hashin to lock versions. We use npm to manage frontend dependencies.

## Python

### Adding Python Dependencies

We use `hashin <https://pypi.org/project/hashin>`_ to manage package installs. It helps you manage your ``requirements.txt`` file by adding hashes to ensure that the installed package versions match your expectations.

hashin is automatically installed in local developer environments.

> If you add just the package name the script will automatically get the latest version for you.

```bash
hashin -r {requirements} {dependency}=={version}
```

This will add hashes and sort the requirements for you adding comments to
show any package dependencies.

When it's run check the diff and make edits to fix any issues before
submitting a PR with the additions.

### Managing Python Dependencies

We have 2 requirements files for python dependencies:

- prod.txt
- dev.txt

Prod dependencies are used by our django app in runtime.
They are strictly required to be installed in the production environment.

```bash
make update_deps_prod
```

Dev dependencies are used by our django app in development or by tools we use for linting, testing, etc.

```bash
make update_deps
```

We use dependabot to automatically create pull requests for updating dependencies. This is configured in the `.github/dependabot.yml` file targeting files in our requirements directory.

### Managing transitive dependencies

In local development and in CI we install packages using pip, reading from one or more requirements files and always passing the `--no-deps` flag.
This prevents pip from installing transitive dependencies.

We do this because it gives us control over the full dependency chain - we know exactly which version of what package is installed so we can fully reproduce & trust environments.

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
