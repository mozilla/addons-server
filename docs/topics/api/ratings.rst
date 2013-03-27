.. _ratings:

===========
Ratings API
===========

These endpoints allow the retrieval, creation, and modification of ratings on
apps in Marketplace.

.. note:: All ratings methods require authentication.


_`Listing`
==========

To get a list of ratings from the Marketplace::

    GET /api/apps/rating/

This endpoints accepts various optional query string parameters to filter the
results:

* `limit`: the number of results returned per page. Default `20`.
* `offset`: the number of results to offset by. Default `0`
* `app`: the ID of the app whose ratings are to be returned.
* `user`: the ID of the user whose ratings are to be returned.

The API returns a list of ratings sorted by date created, descending::

  {
      "meta": {
          "limit": 20,
          "next": "/api/apps/rating/?limit=20&offset=20",
          "offset": 0,
          "previous": null,
          "total_count": 391
      },
      "info": {
          "average": 3.4,
          "slug": "marble-run"
      },
      "objects": [
          {
              "app": "/api/apps/app/18/",
              "body": "This app is top notch. Aces in my book!",
              "rating": 5,
              "resource_uri": "/api/apps/rating/19/",
              "user": {
                  "id": "198",
                  "resource_uri": "",
                  "username": "chuck"
              }
          },
          ...
      ]
  }


_`Detail`
=========

To get a single rating from the Marketplace using its `resource_uri` from the 
`listing`_::

    GET /api/apps/rating/<ID>/

The API returns a representation of the requested resource::

  {
      "app": "/api/apps/app/18/",
      "body": "This app is top notch. Aces in my book!",
      "rating": 5,
      "resource_uri": "/api/apps/rating/19/",
      "user": {
          "id": "198",
          "resource_uri": "",
          "username": "chuck"
      }
  }


_`Create`
=========

To create a rating from the Marketplace::

    POST /api/apps/rating/

The request body should include a JSON representation of the rating to be 
created::

  {
    "app": 18,
    "body": "This app is top notch. Aces in my book!",
    "rating": 5
  }

On success, a 201 is returned.

The following fields are required:

* `app`: an integer containing the ID of the app being rated.
* `body`: a string containing the textual content of the rating.
* `rating`: an integer between (and inclusive of) 1 and 5, indicating the
  numeric value of the rating.

The user is inferred from the authentication details.


Validation
~~~~~~~~~~

The following validation is performed on the request:

- Are the values of `app`, `body`, and `rating` valid? If not, a 400 is returned
  with error messages containing further details.
- If `app` is a paid app, has the authenticating user purchased it? If not, a
  403 is returned.
- Is the authenticating user an author of `app`? If so, a 403 is returned.
- Has the authenticating user previously rated the app? If so, a 409 is
  returned. In these cases, `update`_ should be used.


_`Update`
=========

To update a rating from the Marketplace using its `resource_uri` from the 
`listing`_::

    PUT /api/apps/rating/<ID>/

The request body should include a JSON representation of the rating to be 
created.::

  {
    "body": "It stopped working. All dueces, now.",
    "rating": 2
  }

On success, a 202 is returned.

Validation
~~~~~~~~~~

The following validation is performed on the request:

- Are the values of `body` and `rating` valid? If not, a 400 is returned with
  error messages containing further details.


_`Delete`
=========

To delete a rating from the Marketplace using its `resource_uri` from the 
`listing`_::

    DELETE /api/apps/rating/<ID>/

On success, a 204 is returned.

Validation
~~~~~~~~~~

The following validation is performed on the request:

- Can the authenticating user delete the rating? If not, a 403 is returned. A
  user may delete a rating if:

  - They are the original review author.
  - They are an editor that is not an author of the app.
  - They are in a group with Users:Edit or Addons:Edit privileges
