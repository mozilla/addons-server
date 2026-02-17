# Scanner Pipeline

The scanner pipeline is a security feature to run scanners.

## Scanner Webhooks

A scanner webhook is essentially a URL to a service subscribed to events that
occur on AMO. These webhooks are registed in the AMO (django) admin.

When a [scanner webhook event](#scanner-webhook-events) occurs, AMO will send an
HTTP request to each webhook subscribed to this event. The payload sent to the
webook depends on the event. AMO creates a [scanner result](#scanner-results)
before calling the webhook, and includes a `scanner_result_url` in the payload
that allows the scanner to [asynchronously send its results](#asynchronous-scanning)
back to AMO.

Each service registered as a scanner webhook must be protected with a shared
secret (api) key. Read [the scanners authentication
section](#scanners-authentication) for more information.

### Adding a scanner webhook

Scanner webhooks must be registered in the AMO (django) admin. The following
information must be provided:

- _Name_: the name of the scanner
- _URL_: the full URL of the scanner, which will receive the events
- _API key_: the secret key sent to the scanner to authenticate AMO requests

Add one or more scanner webhook events, see the next section for more
information.

```{note}
Upon creation, a _service account_ will be automatically generated for this
scanner webhook.

A service account is needed to authenticate the scanner against the AMO API.
Make sure to add the relevant permissions to it, depending on what the scanner
needs to access.
```

(scanner-webhook-events)=
### Scanner Webhook Events

#### `during_validation`

This event occurs when a file upload is being validated, which typically happens
when a new version is being submitted to AMO. This is called near the end of the
validation chain.

The payload sent looks like this. Assuming correct permissions, the URL in
`download_url` allows the services notified for this event to download the (raw)
uploaded file. The `scanner_result_url` allows the scanner to send results
asynchronously.

```json
{
  "download_url": "http://olympia.test/uploads/file/42",
  "scanner_result_url": "http://olympia.test/api/v5/scanner/results/123/"
}
```

#### `on_source_code_uploaded`

This event occurs when source code is uploaded, e.g., in DevHub.

The payload sent looks like this:

```json
{
  "addon_id": 85,
  "version_id": 42,
  "download_source_url": "http://olympia.test/downloads/source/42",
  "license_slug": "MPL-2.0",
  "activity_log_id": 2170,
  "scanner_result_url": "http://olympia.test/api/v5/scanner/results/124/"
}
```

### Adding a new event

1. Add a constant for the new event in `src/olympia/constants/scanners.py`. The
   name must start with `WEBHOOK_`. Make sure the new constant is registered in
   `WEBHOOK_EVENTS` (in the same file).
2. In a `tasks.py` file, create a Celery task that calls `call_webhooks(event_name,
payload, upload=none, version=None)`. Make sure this task is assigned to a
   queue in `src/olympia/lib/settings_base.py`.
3. Invoke this Celery task (with `.delay()`) where the event occurs in the code.
4. Update this documentation page.

(scanner-results)=
## Scanner Results

A scanner result stores the output returned by a scanner, and it might be tied
to a [webhook event](#scanner-webhook-events).

Scanners can return a list of _matched rules_. When these rules exist as
[scanner rules](#scanner-rules) on AMO, it becomes possible to execute [scanner
actions](#scanner-actions). This is a core concept of the scanner pipeline,
which essentially allows a scanner to make a change to an add-on version.

(scanner-rules)=
## Scanner Rules

A scanner rule allows scanners to trigger an [action](#scanner-actions).

(scanner-actions)=
## Scanner Actions

A scanner action is some logic that can be applied to an add-on version. For
example, flagging a version for manual review is a scanner action.

These actions are defined in `src/olympia/scanners/actions.py`.

## Scanners

(scanners-authentication)=
### Authentication

#### Authenticating incoming webhook calls

Scanners must verify the incoming requests using the `Authorization` header and
not allow unauthenticated requests. For every webhook call, AMO will send this
header using the _API key_ defined in the Django admin as follows:

```
Authorization: HMAC-SHA256 <hexdigest>
```

`<hexdigest>` is the [HMAC-SHA256][hmac] hex digest of the request's body with
the _API key_ used as the secret key. Make sure to hash the _raw_ request's
body.

#### Authenticating asynchronous result submissions

When sending results asynchronously via PATCH to the `scanner_result_url`,
scanners must authenticate using JWT credentials. Each scanner webhook has an
automatically created service account, and the JWT keys for this account are
displayed in the Django admin after creating the webhook.

Use the JWT key and secret to generate a JWT token and include it in the
`Authorization` header when making PATCH requests to submit results
asynchronously.

### API response

Scanners can choose to return results synchronously or asynchronously:

#### Synchronous response

Scanners can return a JSON response immediately that contains the following fields:

- `version`: the scanner version
- `matchedRules`: an array of matched rule identifiers (string)

(asynchronous-scanning)=
#### Asynchronous response

Scanners can also return a quick acknowledgment response (or any response) and
send their results later using the `scanner_result_url` provided in the webhook
payload. This is useful for long-running scans.

To send results asynchronously:

1. The scanner receives a webhook call with a `scanner_result_url` in the payload
2. The scanner returns a quick response (e.g., HTTP 202 Accepted)
3. The scanner performs its analysis
4. The scanner sends a PATCH request to the `scanner_result_url` with the results

The PATCH request must be authenticated using the [service account JWT
credentials](#scanners-authentication) and include a JSON body with a `results`
field:

```json
{
  "results": {
    "version": "1.0.0",
    "matchedRules": []
  }
}
```

The `results` field should contain the same data structure as a synchronous
response would return.

### Creating a new scanner

We provide a library to quickly develop new scanners written with Node.js:
[addons-scanner-utils][].

Start by installing the dependencies using `npm`:

```text
npm add express body-parser safe-compare addons-scanner-utils
```

Next, create an `index.js` containing the code of the scanner:

```js
import { createExpressApp } from "addons-scanner-utils";

const handler = (req, res) => {
  console.log({ data: req.body });

  // Option 1: Synchronous response
  res.json({ version: "1.0.0" });

  // Option 2: Asynchronous response (for long-running scans)
  // res.status(202).json({ message: "Scan started" });
  // // Perform scanning asynchronously and later send results to:
  // // req.body.scanner_result_url
};

const app = createExpressApp({
  apiKeyEnvVarName: "NEW_SCANNER_API_KEY",
})(handler);
const port = process.env.PORT || 20000;

app.listen(port, () => {
  console.log(`new-scanner is running on port ${port}`);
});
```

Start the new scanner with `node`:

```text
NEW_SCANNER_API_KEY=new-scanner-api-key node index.js
new-scanner is running on port 20000
```

Register the new scanner on AMO:

![](../../_static/images/scanner-pipeline-create-new-scanner.png)

When the new scanner is created, the Django admin will display the JWT keys for
the service account bound to this new scanner. Keep these credentials safe.

![](../../_static/images/scanner-pipeline-jwt-keys.png)

When uploading a new file, you should see the following in the console:

```js
{
  data: {
    download_url: "http://olympia.test/uploads/file/fa7868396b7e44ef8a0711f608f534f7/?access_token=w0Tl7qmJqBMQ4gtitKbcdKozulWVQWhkU0wEA10N",
    scanner_result_url: "http://olympia.test/api/v5/scanner/results/123/"
  }
}
```

[addons-scanner-utils]: https://github.com/mozilla/addons-scanner-utils
[hmac]: https://en.wikipedia.org/wiki/HMAC
