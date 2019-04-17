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
to if necessary.

Except for the ``message``, all strings have a maximum length of 255 characters
and should be truncated by the client where necessary.

.. http:post:: /api/v4/abuse/report/addon/

    :<json string addon: The id, slug, or guid of the add-on to report for abuse (required).
    :<json string message: The body/content of the abuse report (required).
    :<json string|null report_entry_point: The report entry point. The accepted values are documented in the :ref:`table below <abuse-report_entry_point-parameter>`.
    :<json string|null addon_install_method: The add-on install method. The accepted values are documented in the :ref:`table below <abuse-addon_install_method-parameter>`.
    :<json string|null addon_install_origin: The add-on install origin.
    :<json string|null addon_name: The add-on name in the locale used by the client.
    :<json string|null addon_signature: The add-on signature state. The accepted values are documented in the :ref:`table below <abuse-addon_signature-parameter>`.
    :<json string|null addon_summary: The add-on summary in the locale used by the client.
    :<json string|null addon_version: The add-on version string.
    :<json string|null app: The :ref:`application <addon-detail-application>` used by the client. Can be either ``firefox`` or ``android``.
    :<json string|null appversion: The application version used by the client.
    :<json string|null lang: The language code of the locale used by the client for the application.
    :<json string|null client_id: The client's hashed telemetry ID.
    :<json string|null install_date: The add-on install date.
    :<json string|null operating_system: The client's operating system.
    :<json string|null operating_system_version: The client's operating system version.
    :<json string|null reason: The reason for the report. The accepted values are documented in the :ref:`table below <abuse-reason-parameter>`.
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
    :>json string|null report_entry_point: The report entry point.
    :>json string|null addon_install_method: The add-on install method.
    :>json string|null addon_install_origin: The add-on install origin.
    :>json string|null addon_name: The add-on name in the locale used by the client.
    :>json string|null addon_signature: The add-on signature state.
    :>json string|null addon_summary: The add-on summary in the locale used by the client.
    :>json string|null addon_version: The add-on version string.
    :>json string|null app: The application used by the client.
    :>json string|null appversion: The application version used by the client.
    :>json string|null lang: The language code of the locale used by the client for the application.
    :>json string|null client_id: The client's hashed telemetry ID.
    :>json string|null install_date: The add-on install date.
    :>json string|null operating_system: The client's operating system.
    :>json string|null operating_system_version: The client's operating system version.
    :>json string|null reason: The reason for the report.

.. _abuse-report_entry_point-parameter:

 Accepted values for the ``report_entry_point`` parameter:

 ===========================  =================================================
                       Value  Description
 ===========================  =================================================
                   uninstall  Report button shown at uninstall time
                        menu  Report menu in Add-ons Manager
        toolbar_context_menu  Report context menu on add-on toolbar
 ===========================  =================================================

.. _abuse-addon_install_method-parameter:

 Accepted values for the ``addon_install_method`` parameter:

 ===========================  =================================================
                       Value  Description
 ===========================  =================================================
                    amwebapi  Add-on Manager Web API
                        link  Direct Link
              installtrigger  InstallTrigger API
           install_from_file  Local File
       management_webext_api  WebExt Management API
               drag_and_drop  Drag & Drop
                    sideload  Sideload
 ===========================  =================================================

.. _abuse-addon_signature-parameter:


 Accepted values for the ``addon_signature`` parameter:

 ===========================  =================================================
                       Value  Description
 ===========================  =================================================
         curated_and_partner  Curated and partner
                     curated  Curated
                     partner  Partner
                 non_curated  Non-curated
                    unsigned  Unsigned
 ===========================  =================================================

.. _abuse-reason-parameter:

 Accepted values for the ``reason`` parameter:

 ===========================  ================================================================
                       Value  Description
 ===========================  ================================================================
                     harmful  Damages computer and/or data
         spam_or_advertising  Creates spam or advertising
            browser_takeover  Changes search / homepage / new tab page without informing user
                      broken  Doesn’t work, breaks websites, or slows Firefox down
                   offensive  Hateful, violent, or illegal content
  does_not_match_description  Doesn't match description
                    unwanted  Wasn't wanted / impossible to get rid of
                       other  Something else
 ===========================  ================================================================



------------------------------
Submitting a user abuse report
------------------------------

.. _`userabusereport-create`:

The following API endpoint allows an abuse report to be submitted for a user account
on https://addons.mozilla.org.  Authentication is not required, but is recommended
so reports can be responded to if necessary.

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
