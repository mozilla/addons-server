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

Multiple Databases
------------------

At this point, most people get by running Django apps with one database.  Crazy,
I know!  The good news: there was a Summer of Code project this year to add
multiple-database support.  The bad news: it hasn't been merged with Django yet,
but is a high priority in the
`1.2 release <http://code.djangoproject.com/wiki/Version1.2Roadmap>`_ (scheduled
for March 9, 2010).  At first I was leaning towards us running the mutlti-db
branch from http://github.com/alex/django/tree/multiple-db, but I'm hesitant
because we'd miss out on other fixes going on in trunk code right now.  We could
do our own branch management, but I don't know how much time that would take.

Since the multi-db branch just provides a better low-level API, we'll have to
roll our own master-slave logic anyways, most likely using Django's
:class:`Managers <django.db.models.Manager>`.  There's some prior art at
http://github.com/mmalone/django-multidb/.  Given this, I don't think we'd gain
a lot by running off the github multi-db branch.


Working off Trunk
--------------------

It's pretty common to use /trunk rather than a standard release in the Django
community.  The Django developers are very sensitive about breaking
backwards compatibility, and are cautious about what goes into trunk, so it's a
relatively safe option.  Since pip lets us pin a git requirement to a certain
hash, we'll all still be running the same Django version, and we won't ever hit
big hurdles upgrading to the next major release.  Test also help here, a lot.

I (jbalogh) am offering to manage upgrades and any breakages.  I'll probably
move the Django pointer in between our releases so it's not constantly
disruptive, and we'll have a full QA cycle to make sure everything still works.


Migrations
----------

We're going to use `South <http://south.aeracode.org/>`_.  Here's the
`Quick Start Guide <http://south.aeracode.org/wiki/QuickStartGuide>`_, the
`tutorial <http://south.aeracode.org/wiki/Tutorial1>`__, and the rest of the
`South docs <http://south.aeracode.org/wiki/Documentation>`_.


CSRF
----

The standard version of CSRF in Django used to be middleware that rewrote any
forms it could find in your HTML content to include a hidden token.  That's
going away now.

Details on the new version can be found at
http://docs.djangoproject.com/en/dev/ref/contrib/csrf/.  I'll have to write
something to make the ``{% csrf_token %}`` tag work with our Jinja templates,
but the rest will be the same.  It will probably look like
``{% csrf_token() %}``.


Testing
-------

Print it out and read it before you go to bed:
http://docs.djangoproject.com/en/dev/topics/testing/

Don't bother with the doctests stuff, we won't use those.  We'll write lots of
unit tests and make heavy use of the :mod:`test client <django.test.client>`.

We're going to use
`nose <http://somethingaboutorange.com/mrl/projects/nose/0.11.1/>` for test
discovery and running.  It provides a lot of options like running only the
failing tests and outputting XUnit-style XML (which is cool if you want to
Hudson to understand your test results).  Here's a nice app to integrate
nose with Django: http://github.com/jbalogh/django-nose.


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
