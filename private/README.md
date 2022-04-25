# Private tools

This folder should contain some of our private tools. In the following, we describe how to use them locally.

## Scanners

Make sure to clone:

1. the `customs` repo in `private/addons-customs-scanner`

Specify the [`docker-compose.private.yml`](../docker-compose.private.yml) file to `docker-compose` (together with the default [`docker-compose.yml`](../docker-compose.yml) file) to build the Docker images:

```
$ docker-compose -f docker-compose.yml -f docker-compose.private.yml build
```

Run the local environment with the private services:

```
$ docker-compose -f docker-compose.yml -f docker-compose.private.yml  up -d
```

### customs

A waffle switch is used to enable/disable the `customs` Celery task:

```
$ make shell
$ [root@<docker>:/code#] ./manage.py waffle_switch enable-customs on
```

## Yara

If you have access to `yara`, you should first clone it in `private/addons-yara`.

A waffle switch is used to enable/disable the `yara` Celery task:

```
$ make shell
$ [root@<docker>:/code#] ./manage.py waffle_switch enable-yara on
```
