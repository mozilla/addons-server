==============
Add-on Authors
==============

.. note::

    These APIs are not frozen and can change at any time without warning.
    See :ref:`the API versions available<api-versions-list>` for alternatives
    if you need stability - note the following APIs are only available on v5+ though.

-----------
Author List
-----------

.. _addon-author-list:

This endpoint returns a list of all the authors of an add-on.  No pagination is supported.
New authors are created as pending authors, which become authors once the user has confirmed.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on.


.. http:get:: /api/v5/addons/addon/(int:id|string:slug|string:guid)/authors/


-------------
Author Detail
-------------

.. _addon-author-detail:

This endpoint allows the properties of an add-on author to be retrieved, given a user (account) id.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on.


.. http:get:: /api/v5/addons/addon/(int:id|string:slug|string:guid)/authors/(int:user_id)/

    .. _addon-author-detail-object:

    :>json int user_id: The user id for an author.
    :>json string name: The name for an author.
    :>json string email: The email address for an author.
    :>json string role: The :ref:`role <addon-author-detail-role>` the author holds on this add-on.
    :>json boolean listed: If ``true`` the user will be listed as an add-on author publicly on the add-on detail page. (If ``false`` the user is not exposed as an author.)
    :>json int position: The position the author should be returned in the list of authors of the add-on :ref:`detail <addon-detail-object>`. Order is ascending so lower positions are placed earlier.


.. _addon-author-detail-role:

    Possible values for the ``role`` field:

    ==============  ==============================================================
             Value  Description
    ==============  ==============================================================
         developer  A developer of the add-on. Developers can change all add-on
                    metadata and create, delete, and edit versions of the add-on.
             owner  An owner of the add-on. Owners have all the abilities of a
                    developer, plus they can add, remove, and edit add-on authors,
                    and delete the add-on.
    ==============  ==============================================================

-----------
Author Edit
-----------

.. _addon-author-edit:

This endpoint allows the properties of an add-on author to be edited.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an owner of the add-on.

    .. warning::
        If you change your own author role to developer from owner you will lose permission to make any further author changes.

.. http:patch:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/authors/(int:user_id)/

    .. _addon-author-edit-request:

    :<json string role: The :ref:`role <addon-author-detail-role>` the author holds on this add-on.  Add-ons must have at least one owner author.
    :<json boolean listed: If ``true`` the user will be listed as an add-on author publicly on the add-on detail page. (If ``false`` the user is not exposed as an author.)  Add-ons must have at least one listed author.
    :<json int position: The position the author should be returned in the list of authors of the add-on :ref:`detail <addon-detail-object>`. Order is ascending so lower positions are placed earlier.


-------------
Author Delete
-------------

.. _addon-author-delete:

This endpoint allows an add-on author to be removed from an add-on.
Add-ons must have at least one owner, and at least one listed author.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an owner of the add-on.

    .. warning::
        If you delete yourself as an add-on author you will lose all access to the add-on.

.. http:delete:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/authors/(int:user_id)/


---------------------
Pending Author Create
---------------------

.. _addon-pending-author-create:

This endpoint allows an owner to invite a user to become an author of an add-on - the user will be sent an email notifying them of the invitation.
A pending author is created for the add-on, and once they confirm the invitation, they will be an author of that add-on.
Authors will be given the position at the end of the list of authors when confirmed.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an owner of the add-on.

.. http:post:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/pending-authors/

    .. _addon-pending-author-create-request:

    :<json int user_id: The user to invited to become an author of this add-on.
    :<json string role: The :ref:`role <addon-author-detail-role>` the author will hold on this add-on.
    :<json boolean listed: If ``true`` the user will be listed as an add-on author publicly on the add-on detail page once confirmed. (If ``false`` the user will not be exposed as an author.)


----------------------
Pending Author Confirm
----------------------

.. _addon-pending-author-confirm:

This endpoint allows a user to confirm they want to be an author of an add-on.
Authors will be given the position at the end of the list of authors when confirmed.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be invited to be an author (to be a pending author).

.. http:post:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/pending-authors/confirm/


----------------------
Pending Author Decline
----------------------

.. _addon-pending-author-decline:

This endpoint allows a user to decline the invitation to be an author of an add-on.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be invited to be an author (to be a pending author).

.. http:post:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/pending-authors/decline/


-------------------
Pending Author List
-------------------

.. _addon-pending-author-list:

This endpoint returns a list of all the pending authors of an add-on.  No pagination is supported.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on.


.. http:get:: /api/v5/addons/addon/(int:id|string:slug|string:guid)/pending-authors/


---------------------
Pending Author Detail
---------------------

.. _addon-pending-author-detail:

This endpoint allows the properties of a pending add-on author to be retrieved, given a user (account) id.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on.


.. http:get:: /api/v5/addons/addon/(int:id|string:slug|string:guid)/pending-authors/(int:user_id)/

    .. _addon-pending-author-detail-object:

    :>json int user_id: The user id for a pending author.
    :>json string name: The name for a pending author.
    :>json string email: The email address for a pending author.
    :>json string role: The :ref:`role <addon-author-detail-role>` the author will hold on this add-on.
    :>json boolean listed: If ``true`` the user will be listed as an add-on author publicly on the add-on detail page once confirmed. (If ``false`` the user will not be exposed as an author.)


-------------------
Pending Author Edit
-------------------

.. _addon-pending-author-edit:

This endpoint allows the properties of a pending add-on author to be edited.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an owner of the add-on.

.. http:patch:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/pending-authors/(int:user_id)/

    .. _addon-pending-author-edit-request:

    :<json string role: The :ref:`role <addon-author-detail-role>` the author will hold on this add-on.
    :<json boolean listed: If ``true`` the user will be listed as an add-on author publicly on the add-on detail page once confirmed. (If ``false`` the user will not be exposed as an author.)


---------------------
Pending Author Delete
---------------------

.. _addon-pending-author-delete:

This endpoint allows a pending add-on author to be deleted, so the user is no longer able to confirm to become an author of the add-on.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an owner of the add-on.

.. http:delete:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/pending-authors/(int:user_id)/
