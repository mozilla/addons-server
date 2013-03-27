.. _ratings:

===========
Ratings API
===========

This API allows access to ratings and reviews of apps.

Ratings
=======

To get a list of ratings for an app::

    GET /api/apps/rating/?app=<app-id>

The API accepts various query string parameters for filtering the results:

* `app` (required): the ID of the app rated.
* `user` (optional): the ID of the author of a rating.
* `pk` (optional): the ID of a particular rating.
* `is_latest` (optional): Whether this is the latest rating by the rating
  author.
* `created` (optional): The date of the posting of the rating.


The API returns a list of ratings, in order they were posted::

        {[
         "meta": {"limit": 20,
                  "next": null,
                  "offset": 0,
                  "previous": null,
                  "total_count": 2},
         "info": {
            "average": 3.4,
            "slug": "marble-run"
         },
         "user": {
            "can_rate": true,
            "has_rated": false
         }
         "objects": [{
            "id": 17,
            "app": "/api/apps/app/21",
            "user": 2165,
            "rating": 3,
            "title": "title text",
            "body": "body text",
            "editorreview": true
         }, ...]
        }
