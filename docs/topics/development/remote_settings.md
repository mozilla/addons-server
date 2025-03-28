# Remote Settings

This page explains how to set up [Remote Settings][] locally, which can be
useful when working on the [Blocklist feature](../blocklist.md). AMO must be
running locally first. Make sure it's available at <http://olympia.test/>.

## Configure addons-server

Add the following configuration variables to the `local_settings.py` file:

```
# When using Docker Desktop - `host.docker.internal` is a special host to allow
# containers to get access to the host system, but that won't work on Linux.
REMOTE_SETTINGS_API_URL = "http://host.docker.internal:8888/v1/"
REMOTE_SETTINGS_WRITER_URL = "http://host.docker.internal:8888/v1/"

# For Linux, you need to find the IP address of the Remote Settings container:
# REMOTE_SETTINGS_API_URL = "http://172.17.0.1:8888/v1/"
# REMOTE_SETTINGS_WRITER_URL = "http://172.17.0.1:8888/v1/"
```

Next, reload everything by running `make up`.

At this point, AMO should be able to find the Remote Settings local server that
we're going to set up next.

## Set up Remote Settings

In order to set up Remote Settings, follow these steps:

1. Clone <https://github.com/mozilla/remote-settings>
2. Run `make start` in the `remote-settings` repository
3. Add `127.0.0.1 autograph` to your `/etc/hosts` file

Verify that Remote Settings is healthy:

```
curl http://127.0.0.1:8888/v1/__heartbeat__
{
  "storage": true,
  "permission": true,
  "cache": true,
  "attachments": true,
  "signer": true
}
```

## Configure the user/permissions

First, we need an `admin` account. We can create one with the Remote Settings
API:

```
curl -X PUT -H 'Content-Type: application/json' \
  -d '{"data": {"password": "s3cr3t"}}' \
  http://127.0.0.1:8888/v1/accounts/admin
```

Next, we need a user for AMO:

```
curl -X PUT -H 'Content-Type: application/json' \
  -d  '{"data": {"password": "amo_remote_settings_password"}}' \
  http://127.0.0.1:8888/v1/accounts/amo_remote_settings_username
```

We then need to give this user _write_ access to the `staging` bucket so that it
can create the `addons-bloomfilters` collection. This is where AMO will write
the new records, which will be propagated to the public bucket/collection
automatically:

```
curl -X PUT -H 'Content-Type: application/json' \
  -d '{"permissions": {"write": ["account:amo_remote_settings_username"]}}' \
  -u admin:s3cr3t \
  http://127.0.0.1:8888/v1/buckets/staging
```

```
curl -X PUT -H 'Content-Type: application/json' \
  -u amo_remote_settings_username:amo_remote_settings_password \
  http://127.0.0.1:8888/v1/buckets/staging/collections/addons-bloomfilters
```

At this point, AMO should be able to authenticate to Remote Settings. This can
be verified with the following command:

```
curl http://olympia.test/services/monitor.json
{
    "cinder": {
        "state": true,
        "status": ""
    },
    "rabbitmq": {
        "state": true,
        "status": ""
    },
    "remotesettings": {
        "state": true,
        "status": ""
    },
    "signer": {
        "state": true,
        "status": ""
    }
}
```

After AMO uploads records, the Remote Settings `addons-bloomfilters` collection
will be available at:
<http://127.0.0.1:8888/v1/buckets/blocklists/collections/addons-bloomfilters/changeset?_expected=0>

We are done \o/

[Remote Settings]: https://remote-settings.readthedocs.io/en/latest/index.html
