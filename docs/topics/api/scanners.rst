============
Scanners
============

.. note::

    These APIs are subject to change at any time and are for internal use only.


---------------------
Post - Push results
---------------------

.. _scanner-result-push:

This endpoint allows a scanner to push results for an existing version.

    .. note::
        Requires JWT authentication using the service account credentials
        associated with the scanner webhook.

.. http:post:: /api/v5/scanner/results/

    :<json integer version_id: The primary key of the add-on version.
    :<json object results: The scanner results.
    :statuscode 201: Result created successfully.
    :statuscode 400: Invalid payload.
    :statuscode 403: Authentication failed or the authenticated user is not
        the service account of an active webhook with a push event.
    :statuscode 409: One or more of the matched rules have already been pushed
        for this version.


----------------------
Patch - Update results
----------------------

.. _scanner-result-patch:

This endpoint allows to update scanner results.

    .. note::
        Requires JWT authentication using the service account credentials
        associated with the scanner webhook.

.. http:patch:: /api/v5/scanner/results/(int:pk)/

    :query string id: The scanner result ID.
    :<json object results: The scanner results.
    :statuscode 204: Results successfully updated.
    :statuscode 400: Invalid payload.
    :statuscode 409: Scanner results already recorded.


------------
Query rules
------------

.. _scanner-query-rules:

These endpoints allow authorized users to create and run ``ScannerQueryRule``
objects and to read their matches.

    .. note::
        Requires JWT authentication. The authenticated user must belong to a
        group with the ``Admin:ScannersQueryView`` permission for read
        operations, and ``Admin:ScannersQueryEdit`` for create, update, delete,
        run and abort operations.

A rule can only be edited while it is in the ``New`` state; once it has been
scheduled or run its definition is frozen and a new rule should be created to
iterate on it.

The ``scanner`` field accepts ``3`` (yara) or ``5`` (narc). The ``state`` field
is one of ``1`` (New), ``2`` (Running), ``3`` (Aborted), ``4`` (Completed),
``5`` (Aborting) or ``6`` (Scheduled).


List / create rules
-------------------

.. http:get:: /api/v5/scanner/query-rules/

    Return a paginated list of query rules, most recently created first.

    :>json int count: The number of rules.
    :>json array results: The array of rules (see the fields below).
    :statuscode 200: Rules returned successfully.
    :statuscode 401: Authentication failed.
    :statuscode 403: The authenticated user lacks the required permission.

.. http:post:: /api/v5/scanner/query-rules/

    Create a new query rule. The definition is validated (YARA/NARC
    compilation and, for YARA, that the rule name matches the ``name`` field).

    :<json string name: The exact name of the rule used by the scanner (required).
    :<json int scanner: ``3`` (yara) or ``5`` (narc) (required).
    :<json string definition: The rule definition (required).
    :<json string pretty_name: Human-readable name (optional).
    :<json string description: Human-readable description (optional).
    :<json object configuration: Scanner-specific configuration (optional).
    :<json boolean run_on_disabled_addons: Run on force-disabled add-ons too (optional).
    :<json boolean run_on_current_version_only: Run on the current listed version only (optional).
    :<json int run_on_specific_channel: Restrict to a channel, ``1`` (unlisted) or ``2`` (listed) (optional).
    :<json boolean exclude_promoted_addons: Exclude promoted add-ons (optional).
    :>json int id: The primary key of the created rule.
    :>json int state: The rule state (``1`` / New for a freshly created rule).
    :>json string state_display: Human-readable state.
    :>json string scanner_display: Human-readable scanner name.
    :>json string completion_rate: Progress string while running, otherwise ``null``.
    :>json int results_count: Number of matches recorded so far.
    :statuscode 201: Rule created successfully.
    :statuscode 400: Invalid payload (e.g. the definition does not compile).
    :statuscode 401: Authentication failed.
    :statuscode 403: The authenticated user lacks the required permission.


Retrieve / update / delete a rule
---------------------------------

.. http:get:: /api/v5/scanner/query-rules/(int:pk)/

    Return a single query rule. Poll this endpoint to track a run via the
    ``state``, ``completion_rate`` and ``completed`` fields.

    :statuscode 200: Rule returned successfully.
    :statuscode 401: Authentication failed.
    :statuscode 403: The authenticated user lacks the required permission.
    :statuscode 404: No rule with that id.

.. http:patch:: /api/v5/scanner/query-rules/(int:pk)/

    Update a query rule. Only allowed while the rule is in the ``New`` state.
    Accepts the same writable fields as the create endpoint.

    :statuscode 200: Rule updated successfully.
    :statuscode 400: Invalid payload, or the rule is not in the ``New`` state.
    :statuscode 401: Authentication failed.
    :statuscode 403: The authenticated user lacks the required permission.
    :statuscode 404: No rule with that id.

.. http:delete:: /api/v5/scanner/query-rules/(int:pk)/

    Delete a query rule and its results.

    :statuscode 204: Rule deleted successfully.
    :statuscode 401: Authentication failed.
    :statuscode 403: The authenticated user lacks the required permission.
    :statuscode 404: No rule with that id.


Run / abort a rule
------------------

.. http:post:: /api/v5/scanner/query-rules/(int:pk)/run/

    Schedule the rule to run. The rule transitions to the ``Scheduled`` state
    and a background task is enqueued.

    :>json int state: The updated state (``6`` / Scheduled).
    :statuscode 202: Run scheduled successfully.
    :statuscode 401: Authentication failed.
    :statuscode 403: The authenticated user lacks the required permission.
    :statuscode 404: No rule with that id.
    :statuscode 409: The rule is not in a state from which it can be run.

.. http:post:: /api/v5/scanner/query-rules/(int:pk)/abort/

    Abort a scheduled or running rule. The rule transitions to the
    ``Aborting`` state.

    :statuscode 200: Abort requested successfully.
    :statuscode 401: Authentication failed.
    :statuscode 403: The authenticated user lacks the required permission.
    :statuscode 404: No rule with that id.
    :statuscode 409: The rule is not in a state from which it can be aborted.


Rule results
------------

.. http:get:: /api/v5/scanner/query-rules/(int:query_rule_pk)/results/

    Return a paginated list of the matches for a rule. Only the
    definition-safe match information is exposed (the files and metadata that
    hit), not the raw scanner output.

    The list can be filtered and ordered with the query parameters below.
    Invalid filter values return a ``400``.

    :query boolean was_blocked: Only results whose version was blocked.
    :query boolean was_promoted: Only results whose add-on was promoted.
    :query boolean was_signed: Only results whose file is signed.
    :query boolean addon_disabled_by_user: Only results whose add-on listing is
        invisible (``true``) or visible (``false``).
    :query int channel: Version channel, ``1`` (unlisted) or ``2`` (listed).
    :query int addon_status: Filter by the add-on status.
    :query int file_status: Filter by the file status.
    :query string sort: Ordering field. One of ``id``, ``addon_adu``
        (add-on average daily users) or ``version_created``. Prefix with ``-``
        for descending order (e.g. ``-addon_adu``). Defaults to ``-id``.
    :>json int count: The number of results.
    :>json array results: The array of results.
    :>json int results[].id: The result id.
    :>json int results[].matched_rule: The id of the rule that matched.
    :>json string results[].addon_guid: The add-on GUID (may be ``null``).
    :>json int results[].version_id: The version id (may be ``null``).
    :>json string results[].version_string: The version number (may be ``null``).
    :>json string results[].channel: The version channel (may be ``null``).
    :>json object results[].matches: The matched files and metadata, keyed by rule name.
    :statuscode 200: Results returned successfully.
    :statuscode 401: Authentication failed.
    :statuscode 403: The authenticated user lacks the required permission.
    :statuscode 404: No rule with that id.
