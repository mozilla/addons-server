# Private tools

This folder should contain some of our private tools. In the following, we
describe how to use them locally.

Make sure to clone:

1. the `customs` repo in `private/addons-customs-scanner`
2. the `addons-builder` repo in `private/addons-builder`

Specify the [`docker-compose.private.yml`](../docker-compose.private.yml) file
to `docker compose` (together with the default
[`docker-compose.yml`](../docker-compose.yml) file) to build the Docker images:

```
$ docker compose -f docker-compose.yml -f docker-compose.private.yml build
```

Run the local environment with the private services:

```
$ make up_private
```

## customs

A waffle switch is used to enable/disable the `customs` scanner:

```
$ make shell
$ [root@<docker>:/code#] ./manage.py waffle_switch enable-customs on
```

## yara

A waffle switch is used to enable/disable the `yara` scanner:

```
$ make shell
$ [root@<docker>:/code#] ./manage.py waffle_switch enable-yara on
```

## source-builder

Both the `enable-scanner-webhooks` and `enable-source-builder` waffle switches
are used to call the source-builder service and display information about it in
the UI, respectively:

```
$ make shell
$ [root@<docker>:/code#] ./manage.py waffle_switch enable-scanner-webhooks on
$ [root@<docker>:/code#] ./manage.py waffle_switch enable-source-builder on
```

Navigate to the [Django admin][scannerwebhook_add] and create a new webhook with
the following information:

- Name: `source-builder`
- URL: `http://source-builder.test:10200/submit`
- API key: `sourcebuildersecret`
- Scanner webhook events: add an entry with `on_source_code_uploaded`

**Note:** this service requires the presence of some mandatory environment
variables, which can be specified in the `private/addons-builder/.env` file. See
the project's README file for more information.

[scannerwebhook_add]: http://olympia.test/en-US/admin/models/scanners/scannerwebhook/add/
