# Devcontainer Setup Guide

This document describes how to set up development via a [devcontainer](https://containers.dev),
either locally or in GitHub Codespaces.

**Using Docker Compose:**

If you prefer using Docker Compose, you can refer to the
[Setup and Configuration](./setup_and_configuration.md) document for more information
on how to configure an environment using Docker Compose.

## 1. Using Visual Studio Code (VS Code)

The Remote - Containers extension in VS Code makes it seamless to work with devcontainers.

**Prerequisites:**

- Install [VS Code](https://code.visualstudio.com/).
- Install the **Remote - Containers** extension.

**Steps:**

1. Open the repository folder in VS Code.
2. When prompted, click **"Reopen in Container"**.
3. VS Code will:
   - Use the configuration from `.devcontainer/devcontainer.json` (including proper volume mounts and port mapping, such as forwarding port 80).
   - Run post-start commands (e.g. `make up` that triggers [`scripts/setup.py`](scripts/setup.py)) to set up required environment variables and directories.

This process abstracts away the need to manually configure port mappings or run lengthy Docker commands.

## 2. GitHub Codespaces

GitHub Codespaces automatically leverages the devcontainer setup defined in your repository.

**Steps:**

1. In your repository on GitHub, click the **"Code"** button and select **"Open with Codespaces"** → **"New codespace"**.
2. Codespaces will:
   - Use the same `.devcontainer/devcontainer.json` to build your container.
   - Mount the repository and forward the ports (with port 80 mapping as required).
   - Execute post-start routines (running `make up` to invoke [`scripts/setup.py`](scripts/setup.py)).

> [!IMPORTANT]
> Within Codespaces, the function `get_olympia_site_url()` in [`scripts/setup.py`](scripts/setup.py) detects the `CODESPACE_NAME` environment variable and sets `SITE_URL` to a Codespaces-compatible URL (e.g., `https://<codespace-name>-80.githubpreview.dev`). This automatic adjustment ensures that the nginx service is accessible without any extra configuration on your part.

## 3. Running a Devcontainer Locally (Command Line & Other IDEs)

> [!IMPORTANT]
> We do not currently support running a devcontainer directly and sshing into it, but we should.
> This would enable development via other IDEs like JetBrains, VIM, Atom, etc.

Please look at the [Dev Container CLI](https://code.visualstudio.com/docs/devcontainers/devcontainer-cli)
and open a PR to add support for your favorite IDE.

## Summary

Devcontainers can be very useful for local development by isolating the entire development environment from
the host machine. Instead of running containers directly on the hosst and mounting file changes into the
containers, you can inject your IDE directly into the container.

Devcontainers are also particularly useful for testing. You can deploy a branch to a codespace and enable
verifying a PR from a publically available URL. This allows much faster iteration and testing of PRs
without the need of independently setting up a local development environment.
