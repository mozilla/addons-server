# Scanner Pipeline

The scanner pipeline is a security feature to run scanners.

## Scanner Webhooks

A scanner webhook is essentially a URL to a service subscribed to events that
occur on AMO. These webhooks are registed in the AMO (django) admin.

When a [scanner webhook event](#scanner-webhook-events) occurs, AMO will send an
HTTP request to each webhook subscribed to this event. The payload sent to the
webook depends on the event. The response from each webhook will lead to the
creation of a [scanner result](#scanner-results).

Each service registered as a scanner webhook must be protected with a secret
(bearer) token. AMO will include this token in the `Authorization` header of
each HTTP request made to the webhook.

### Adding a scanner webhook

Scanner webhooks must be registered in the AMO (django) admin. The following
information must be provided:

- _Name_: the name of the scanner
- _URL_: the full URL of the scanner, which will receive the events
- _API key_: the secret key sent to the scanner to authenticate AMO requests

Add one or more scanner webhook events, see the next section for more
information.

(scanner-webhook-events)=
### Scanner Webhook Events

#### `during_validation`

This event occurs when a file upload is being validated, which typically happens
when a new version is being submitted to AMO. This is called near the end of the
validation chain.

The payload sent looks like this. Assuming correct permissions, the URL in
`download_url` allows the services notified for this event to download the (raw)
uploaded file.

```json
{
  "download_url": "http://olympia.test/uploads/file/42"
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
