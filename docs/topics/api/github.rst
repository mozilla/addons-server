===============
GitHub Webhooks
===============

This API provides an endpoint that works with GitHub to provide add-on validation as a GitHub webhook. This end point is designed to be called specifically from GitHub and will only send API responses back to `api.github.com`.

To set this up on a GitHub repository you will need to:

* Go to `Settings > Webhooks & Services`
* Add a new Webhook with Payload URL of `https://addons.mozilla.org/api/v3/github/`
* Click `Update webhook`

The validator will run when you create or alter a pull request.

.. http:post::/api/v3/github/

    **Request:**

    A `GitHub API webhook <https://developer.github.com/v3/repos/hooks/>`_ body. Currently only `pull_request` events are processed, all others are ignored.

    **Response:**

    :statuscode 200: request has been processed and a pending message sent back to GitHub.
    :statuscode 202: request is not a `pull_request`, it's been accepted, but not processed.
    :statuscode 422: body is invalid.
