.. _django:

======================
Django, the Good Parts
======================

The `Django docs <http://docs.djangoproject.com/en/dev/>`_ are the best way to
learn about Django.  These aren't your normal docs.  They're useful.

Read through the
`overview <http://docs.djangoproject.com/en/dev/intro/overview/>`_, go through
the `tutorial <http://docs.djangoproject.com/en/dev/intro/tutorial01/>`_, or
jump into some other part that interests you.  My awesomebar loves these pages:

 * `Querysets <http://docs.djangoproject.com/en/dev/ref/models/querysets/>`_
 * `Model Fields <http://docs.djangoproject.com/en/dev/ref/models/fields/>`_
 * `Caching <http://docs.djangoproject.com/en/dev/topics/cache/>`_
 * `View Shortcuts <http://docs.djangoproject.com/en/dev/topics/http/shortcuts/>`_
 * `Testing <http://docs.djangoproject.com/en/dev/topics/testing/>`_
 * `Urls <http://docs.djangoproject.com/en/dev/topics/http/urls/>`_
 * `Forms <http://docs.djangoproject.com/en/dev/topics/forms/>`_

I'm not going to go into detail on anything that's covered in the docs, since
they do it better.


CSRF
----


In Django 1.2, `csrf <http://docs.djangoproject.com/en/dev/ref/contrib/csrf/>`_
was improved by embedding ``{% csrf_token %}`` inside forms instead of using
middleware to rewrite HTML strings.  But since we're using Jinja for templating,
that doesn't work.

Instead, use ::

    {{ csrf() }}

inside templates to embed the CSRF token Django expects.  See
:src:`apps/admin/templates/admin/flagged_addon_list.html` for an example.


Testing
-------

Print it out and read it before you go to bed:
http://docs.djangoproject.com/en/dev/topics/testing/

Don't bother with the doctests stuff, we won't use those.  We'll write lots of
unit tests and make heavy use of the :mod:`test client <django.test.client>`.

See more in :ref:`testing`.


Best Practices
--------------

This slide deck has a fantastic overview:
http://media.b-list.org/presentations/2008/djangocon/reusable_apps.pdf

The basic layout for Django is to have a bunch of little apps that work together
to form a site.  The thing that brings these apps together is a "project", which
holds the top-level settings, url routing, and not much else.  The project tells
Django what apps you're using so it knows what models to use, but any other
Python packages can be imported at will.  We like importing things.

Since we're going to have a lot of apps, we're putting them in the /apps
directory, but some namespace trickery lets us import our packages without the
``apps.`` prefix.  If you're adding a new app with models or template tags, add
it to ``INSTALLED_APPS`` so Django loads the model and Jinja loads the template
extensions.

You can find lots of goodies on http://www.b-list.org/weblog/categories/django/.


Migrations
----------

We're going to use `South <http://south.aeracode.org/>`_.  Here's the
`Quick Start Guide <http://south.aeracode.org/wiki/QuickStartGuide>`_, the
`tutorial <http://south.aeracode.org/wiki/Tutorial1>`__, and the rest of the
`South docs <http://south.aeracode.org/wiki/Documentation>`_.
