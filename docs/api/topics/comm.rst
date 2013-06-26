.. _comm:

=============
Communication
=============

API for communication between reviewers and developers.

Thread
======

.. http:get:: /api/v1/comm/thread/

    .. note:: Requires authentication.

    Returns the list of threads where the user has posted a note to, has been CC'd or is an author of the addon that the thread is based on.

    **Request**

    The standard :ref:`list-query-params-label`.

    :param app: id or slug of the app to filter the threads by.
    :type app: int|string

    **Response**

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`threads <thread-response-label>`.
    :type objects: array

.. _thread-response-label:

.. http:get:: /api/v1/comm/thread/(int:id)/

    .. note:: Does not require authentication if the thread is public.

    **Response**

    A thread object, see below for example.

    :status 200: successfully completed.
    :status 403: not allowed to access this object.
    :status 404: not found.

    Example:

    .. code-block:: json

        {
            "id": 2,
            "addon": 2,
            "version": 4,
            "notes": [
                "/api/v1/comm/note/3/"
            ],
            "created": "2013-06-07T15:38:43"
        }

    Notes on the response.

    :param notes: contains all the notes that have been posted to the thread.
    :type notes: array

.. _thread-post-label:

.. http:post:: /api/v1/comm/thread/

    .. note:: Requires authentication.

    **Request**

    :param addon: the id of the addon.
    :type addon: int
    :param version: the id of the version of the addon.
    :type version: int

    **Response**

    :param: A :ref:`thread <thread-response-label>`.
    :status code: 201 successfully created.

.. _thread-delete-label:

.. http:delete:: /api/v1/comm/thread/(int:id)

    .. note:: Requires authentication.

    **Response**

    :status code: 204 successfully deleted.

Note
====

.. _note-response-label:

.. http:get:: /api/v1/comm/note/(int:id)/

    .. note:: Does not require authentication if the note is in a public thread.

    **Request**

    The standard :ref:`list-query-params-label`.

    **Response**

    A thread object, see below for example.

    :status 200: successfully completed.
    :status 403: not allowed to access this object.
    :status 404: not found.

    Example:

    .. code-block:: json

        {
            "id": 3,
            "author": 27,
            "note_type": 1,
            "body": "hi there",
            "created": "2013-06-07T15:40:28",
            "thread": "/api/v1/comm/thread/2/"
        }

    Notes on the response.

    :param note_type: type of action taken with the note.
    :type note_type: int

.. _note-type-label:

    Note type values and associated actions -

    ..

        0 - No Action

        1 - Approval

        2 - Rejection

        3 - Disabled

        4 - MoreInfo

        5 - Escalation

        6 - Reviewer Comment

        7 - Resubmission

.. _note-post-label:

.. http:post:: /api/v1/comm/note/

    .. note:: Requires authentication.

    **Request**

    :param author: the id of the addon.
    :type author: int
    :param thread: the id of the thread to post to.
    :type thread: int
    :param note_type: the type of note to create. See :ref:`supported types <note-type-label>`.
    :type note_type: int
    :param body: the comment text to be attached with the note.
    :type body: string

    **Response**

    :param: A :ref:`note <note-response-label>`.
    :status code: 201 successfully created.

.. _note-delete-label:

.. http:delete:: /api/v1/comm/note/(int:id)

    .. note:: Requires authentication.

    **Response**

    :status code: 204 successfully deleted.
