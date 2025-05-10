# BigQuery Credentials Setup

Setup bigquery credentials for dev on local environment.
This will allow you to connect to the dev BigQuery database
and run queries.

## Steps

### Get dev bigquery credentials json file

[Shell into a dev pod](../dev/shell_into_dev_pod.md)

    a. create a django shell `make djshell`
    b. get the value of `settings.GOOGLE_APPLICATION_CREDENTIALS_BIGQUERY`
    c. exit the django shell and cat the the file
    d. copy the contents to a file on your local machine

```{warning}
This file contains sensitive secrets. Save it in `private/google-application-credentials.json`
which is explicitly gitignored to prevent it from being checked into git.
Do not share this file with anyone.
```

### Run the project locally

    a. update `local_settings.py` to point `GOOGLE_APPLICATION_CREDENTIALS_BIGQUERY` to the file on your local machine
    b. run `make up` to start the django server with this value enabled

### Verify it is working

Verify you can connect to bigquery by running `make djshell` and then:

```python
from olympia.stats.utils import *
client = create_client()
client.project
```

Expect to get a response like:

```bash
In [3]: client.project
Out[3]: 'moz-fx-amo-environment-abc123'
```
