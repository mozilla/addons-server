.. _services:

==========================
Services
==========================

Services contain a couple of scripts that are run as seperate wsgi instances on
the services. Usually they are hosted on seperate domains. They are stand alone
wsgi scripts. The goal is to avoid a whole pile of Django imports, middleware,
sessions and so on that we really don't need.

To run the scripts you'll want a wsgi server, on prod this is Apache and
mod_wsgi. Locally you can optionally use `gunicorn`_, for example::

    pip install gunicorn

Then you can do::

    cd services
    gunicorn --log-level=DEBUG -c wsgi/receiptverify.py -b 127.0.0.1:9000 --debug verify:application

To test::

    curl -d "this is a bogus receipt" http://127.0.0.1:9000/verify/123

.. _`Gunicorn`: http://gunicorn.org/
