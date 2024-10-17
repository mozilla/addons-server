# Static Files in addons-server

This document explains how static files are served in the addons-server project during local development. In production,
static files are served directly from a CDN.

## Overview

addons-server uses a combination of nginx and Django's built-in static file serving capabilities to efficiently serve static files.
These files come from multiple sources:

1. The `./static` folder in the project
2. Python dependencies
3. npm dependencies
4. Compressed/minified files built by `update_assets`

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

The rendering path for static files is as follows:

1. Nginx tries to serve the file if it is available in the `./static` directory.
2. If the file is not found, the request is forwarded to django and served by the static file server.

The static file serve uses our defined `STATICFILES_STORAGE` setting to determine the URL for static files as well as their underlying source file.
During development, we use the `StaticFilesStorage` class which does not map the hashed file names back to their original file names.
Otherwise we use the same `ManifestStaticFilesStorage` class that is used in production, expecting to serve the files from the `STATIC_ROOT` directory.

This allows us to skip `update_assets` in dev mode, speeding up the development process, while still enabling production-like behavior
when configured to do so. The long term goal is to run CI in production mode always to ensure all tests verify against the production
static file build.

To better visualize the impact of the various settings, here is a reference:

Given a static file 'js/devhub/my-file.js':

In `DEV_MODE` the url will look like `/static/js/devhub/my-file.js` no matter what.
However, in production, if `DEBUG` is `False`, the url will append the content hash like this,
`/static/js/devhub/my-file.1234567890.js`. Finally, if `DEBUG` is true, this file will be minified and concatenated with other files and probably look something like this `/static/js/devhub-all.min.1234567890.js`.

The true `production` mode is then when `DEBUG` is `False` and `DEV_MODE` is `False`. But it makes sense
to make these individually toggleable so you can better "debug" js files from a production image.

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
