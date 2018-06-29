=============
Abuse Reports
=============

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. Consider the :ref:`v3 API<api-stable-v3>`
    if you need stability.

The following API endpoint covers abuse reporting

---------------------------------
Submitting an add-on abuse report
---------------------------------

.. _`addonabusereport-create`:

The following API endpoint allows an abuse report to be submitted for an Add-on,
either listed on https://addons.mozilla.org or not.
Authentication is not required, but is recommended so reports can be responded
to if nessecary.

.. http:post:: /api/v4/abuse/report/addon/

    .. _addonabusereport-create-request:

    :<json string addon: The id, slug, or guid of the add-on to report for abuse (required).
    :<json string message: The body/content of the abuse report (required).
    :>json object|null reporter: The user who submitted the report, if authenticated.
    :>json int reporter.id: The id of the user who submitted the report.
    :>json string reporter.name: The name of the user who submitted the report.
    :>json string reporter.username: The username of the user who submitted the report.
    :>json string reporter.url: The link to the profile page for of the user who submitted the report.
    :>json object addon: The add-on reported for abuse.
    :>json string addon.guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :>json int|null addon.id: The add-on id on AMO. If the guid submitted didn't match a known add-on on AMO, then null.
    :>json string|null addon.slug: The add-on slug. If the guid submitted didn't match a known add-on on AMO, then null.
    :>json string message: The body/content of the abuse report.


------------------------------
Submitting a user abuse report
------------------------------

.. _`userabusereport-create`:

The following API endpoint allows an abuse report to be submitted for a user account
on https://addons.mozilla.org.  Authentication is not required, but is recommended
so reports can be responded to if nessecary.

.. http:post:: /api/v4/abuse/report/user/

    .. _userabusereport-create-request:

    :<json string user: The id or username of the user to report for abuse (required).
    :<json string message: The body/content of the abuse report (required).
    :>json object|null reporter: The user who submitted the report, if authenticated.
    :>json int reporter.id: The id of the user who submitted the report.
    :>json string reporter.name: The name of the user who submitted the report.
    :>json string reporter.url: The link to the profile page for of the user who submitted the report.
    :>json string reporter.username: The username of the user who submitted the report.
    :>json object user: The user reported for abuse.
    :>json int user.id: The id of the user reported.
    :>json string user.name: The name of the user reported.
    :>json string user.url: The link to the profile page for of the user reported.
    :>json string user.username: The username of the user reported.
    :>json string message: The body/content of the abuse report.
