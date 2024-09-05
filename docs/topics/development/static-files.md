# Static Files in addons-server

This document explains how static files are served in the addons-server project during local development.

## Overview

addons-server uses a combination of nginx and Django's built-in static file serving capabilities to efficiently serve static files.
These files come from multiple sources:

1. The `./static` folder in the project
2. Python dependencies
3. npm dependencies

## Static File Servers

We use a combination of servers to serve static files:

1. Nginx
2. Django's built-in development server

In development, the nginx server will attempt to serve static files from the `./static` directory mounted into the nginx cointainer.
If the file cannot be found there the request is forwarded to django.
Nginx serves our own static files quickly and any vendor files can be fetched from django directly during development.

In production mode, we mount a data volume both to `web` anb `nginx` containers.
The `web` container exposes the `site-static` directory to nginx that includes the collected static files.

> In actual production environments, we upload the static files to a cloud bucket and serve them directly from the static path.

## Static File Sources

### Project Static Files

Static files specific to the addons-server project are stored in the `./static` directory. These include CSS, JavaScript, images, and other assets used by the application.

In reality there are 3 static directories in our docker compose container:

- `/data/olympia/static`: Contains static files that are mounted directly from the host.
- `/data/olympia/static-build`: Contains static files that are built by `compress_assets`.
- `/data/olympia/site-static`: Contains static files that are collected by the `collectstatic` command.

The only of these directories that is exposed to your host is the `./static` directory.

### Compressing Static Files

We currently use a `ducktape` script to compress our static files.
Ideally we would migrate to a modern tool to replace manual scripting, but for now this works.

Assets are compressed automatically during the docker build, but if you need to manually update files while developing,
the easiest way is to run `make update_assets` which will compress and concatenate static assets as well as  collect all static files
to the `site-static` directory.

### Python Dependencies

Some Python packages include their own static files. These assets are collected by the `collectstatic` command and included in the final static files directory.
During development they are served by the django development server.

### npm Dependencies

We have a (complex) set of npm static assets that are built by the `compress_assets` management command.
During development, these assets are served directly from the node_modules directory using a custom static finder.

## DEBUG Property and Static File Serving

The behavior of static file serving can be controlled using the `DEBUG` environment variable or via setting it directly in
the `local_settings.py` file. Be careful directly setting this value, if DEBUG is set to false, and you don't have sufficient
routing setup to serve files fron nginx only, it can cause failure to serve some static files.

It is best to use  the compose file to control DEBUG.a

This is set in the environment, and in CI environments, it's controlled by the `docker-compose.ci.yml` file.

The `DEBUG` property is what is used by django to determine if it should serve static files or not. In development,
you can manually override this in the make up command, but in general, you should rely on the `docker-compose.ci.yml` file
to set the correct value as this will also set appropriate file mounts.

```bash
make up COMPOSE_FILE=docker-compose.yml:docker-compose.ci.yml
```

This will run addons-server in production mode, serving files from the `site-static` directory.
