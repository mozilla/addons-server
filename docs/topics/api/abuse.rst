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
    
.. note::
    Either addon or user *must* but supplied, but not both.
