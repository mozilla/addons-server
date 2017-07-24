=============
Abuse Reports
=============

The following API endpoint covers abuse reporting

-------------------
Submitting a report
-------------------

.. _`abusereport-create`:

The following API endpoint allows an abuse report to be submitted for an Add-on
or user on addons.mozilla.org.  Authentication is not required, but is recommended
so reports can be responded to if nessecary.

.. http:post:: /api/v3/abuse/report/

    .. _abusereport-create-request:

    :<json string|null addon: if reporting an add-on then the add-on id, slug, or guid of the add-on.
    :<json string|null user: if reporting a user then the user id or username of the user.
    :<json string message: An explanation of the reason for the report (required).
    :>json object|null reporter: The user who submitted the report, if authenticated.
    :>json int reporter.id: The id of the user who submitted the report.
    :>json string reporter.name: The name of the user who submitted the report.
    :>json string reporter.url: The link to the profile page for of the user who submitted the report.
    :>json object|null addon: If this was an add-on abuse report, then the add-on.
    :>json string addon.guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :>json int|null addon.id: The add-on id on AMO.  If the guid submitted didn't match a known add-on on AMO, then null.
    :>json string|null addon.slug: The add-on slug.  If the guid submitted didn't match a known add-on on AMO, then null.
    :>json object|null user: If this was a user abuse report, then the user.
    :>json int user.id: The id of the user who submitted the report.
    :>json string user.name: The name of the user who submitted the report.
    :>json string user.url: The link to the profile page for of the user who submitted the report.

.. note::
    Either addon or user *must* but supplied, but not both.
    If reporting an add-on by guid then the add-on doesn't need to be known to Mozilla beforehand.
