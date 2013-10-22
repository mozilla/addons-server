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

    For ordering params, see :ref:`list-ordering-params-label`.

    :param app: id or slug of the app to filter the threads by.
    :type app: int|string

    **Response**

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`threads <thread-response-label>`.
    :type objects: array
    :param app_threads: If given the **app** parameter, a list of the app's thread IDs and their respective version numbers. The same object is found in the :ref:`thread response <thread-response-label>`.
    :type app_threads: array of objects

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
            "addon": 3,
            "addon_meta": {
                "name": "Test App (kinkajou3969)",
                "slug": "app-3",
                "thumbnail_url": "/media/img/icons/no-preview.png",
                "url": "/app/test-app-kinkajou3969/"
                "review_url": "/reviewers/apps/review/test-app-kinkajou3969/"
            },
            "app_threads": [
                {"id": 1, "version__version": "1.3"},
                {"id": 2, "version__version": "1.6"},
                {"id": 3, "version__version": "1.7"}
            ],
            "created": "2013-06-14T11:54:24",
            "id": 2,
            "modified": "2013-06-24T22:01:37",
            "notes_count": 47,
            "recent_notes": [
                {
                    "author": 27,
                    "author_meta": {
                        "name": "someuser"
                    },
                    "body": "sometext",
                    "created": "2013-06-24T22:01:37",
                    "id": 119,
                    "note_type": 0,
                    "thread": 2
                },
                {
                    "author": 27,
                    "author_meta": {
                        "name": "someuser2"
                    },
                    "body": "sometext",
                    "created": "2013-06-24T21:31:56",
                    "id": 118,
                    "note_type": 0,
                    "thread": 2
                },
                ...
                ...
            ],
            "version": null,
            "version": "1.6",
            "version_is_obsolete": false
        }

    Notes on the response.

    :param recent_notes: contain 5 recently created notes.
    :type recent_notes: array
    :param app_threads: list of app-related thread IDs and their respective version numbers.
    :type app_threads: array of objects
    :param version_number: Version number noted from the app manifest.
    :type version: string
    :param version_is_obsolete: Whether the version of the app of the note is out-of-date.
    :type version: boolean

.. _note-patch-label:

.. http:patch:: /api/v1/comm/thread/(int:thread_id)/

    .. note:: Requires authentication.

    This endpoint can be used to mark all notes in a thread as read.

    **Request**

    :param is_read: set it to `true` to mark the note as read.
    :type is_read: boolean

    **Response**

    :status code: 204 Thread is marked as read.
    :status code: 403 There is an attempt to modify other fields or not allowed to access the object.
    :status code: 400 Thread object not found.

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

.. http:delete:: /api/v1/comm/thread/(int:id)/

    .. note:: Requires authentication.

    **Response**

    :status code: 204 successfully deleted.

Note
====

.. http:get:: /api/v1/comm/thread/(int:thread_id)/note/

    .. note:: Does not require authentication if the thread is public.

    Returns the list of notes that the thread contains.

    **Request**

    The standard :ref:`list-query-params-label`.

    For ordering params, see :ref:`list-ordering-params-label`.

    In addition to above, there is another query param:

    :param show_read: Filter notes by read status. Pass `true` to list read notes and `false` for unread notes.
    :type show_read: boolean

    **Response**

    :param meta: :ref:`meta-response-label`.
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`notes <note-response-label>`.

.. _note-response-label:

.. http:get:: /api/v1/comm/thread/(int:thread_id)/note/(int:id)/

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
            "author": 1,
            "author_meta": {
                "name": "Landfill Admin"
            },
            "body": "hi there",
            "created": "2013-06-14T11:54:48",
            "id": 2,
            "note_type": 0,
            "thread": 2,
            "is_read": false
        }

    Notes on the response.

    :param note_type: type of action taken with the note.
    :type note_type: int
    :param is_read: Whether the note is read or unread.
    :type is_read: boolean

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

.. _note-patch-label:

.. http:patch:: /api/v1/comm/thread/(int:thread_id)/note/(int:id)/

    .. note:: Requires authentication.

    This endpoint can be used to mark an unread note as read.

    **Request**

    :param is_read: set it to `true` to mark the note as read.
    :type is_read: boolean

    **Response**

    :status code: 204 Note marked as read.
    :status code: 403 There is an attempt to modify other fields or not allowed to access the object.
    :status code: 400 Note object not found.

.. _note-post-label:

.. http:post:: /api/v1/comm/thread/(int:thread_id)/note/

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

.. http:delete:: /api/v1/comm/thread/(int:thread_id)/note/(int:id)/

    .. note:: Requires authentication.

    **Response**

    :status code: 204 successfully deleted.


.. _list-ordering-params-label:

List ordering params
~~~~~~~~~~~~~~~~~~~~

Order results by created or modified times, by using `ordering` param.

* *created* - Earliest created notes first.

* *-created* - Latest created notes first.

* *modified* - Earliest modified notes first.

* *-modified* - Latest modified notes first.
