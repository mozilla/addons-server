===============
GitHub Webhooks
===============

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. Consider the :ref:`v3 API<api-stable-v3>`
    if you need stability.

This API provides an endpoint that works with GitHub to provide add-on validation as a GitHub webhook. This end point is designed to be called specifically from GitHub and will only send API responses back to `api.github.com`.

To set this up on a GitHub repository you will need to:

* Go to `Settings > Webhooks & Services`
* Add a new Webhook with Payload URL of `https://addons.mozilla.org/api/v4/github/validate/`
* Click `Send me everything`
* Click `Update webhook`

At this point the validator will be able to get the data, but won't be able to write a response to GitHub. To enable responses to GitHub:

* Go to `Settings > Collaborators`
* Enter `addons-robot` and select the entry
* Click `Add collaborator`
* You will have to wait for a Mozilla person to respond to the invite

If this service proves useful and this service transitions from its Experimental API state, we will remove as many of these steps as possible.

The validator will run when you create or alter a pull request.

.. http:post:: /api/v4/github/validate/

    **Request:**

    A `GitHub API webhook <https://developer.github.com/v4/repos/hooks/>`_ body. Currently only `pull_request` events are processed, all others are ignored.

    **Response:**

    :statuscode 201: request has been processed and a pending message sent back to GitHub.
    :statuscode 200: request is not a `pull_request`, it's been accepted.
    :statuscode 422: body is invalid.
