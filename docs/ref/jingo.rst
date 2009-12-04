.. _jingo:
.. module:: jingo
.. highlight:: jinja

A page about Jingo.
===================

Jingo is an adapter for using
`Jinja2 <http://jinja.pocoo.org/2/documentation/>`_ templates within Django.
Why are we already replacing the templates?  AMO's current PHP templates let you
go hog-wild with logic in the templates, while Django is extremely restrictive.
Jinja loosens those restrictions somewhat, providing a more powerful engine with
the beauty of Django's templates.  The tipping point for me was the verbosity of
doing L10n in Django templates.


Localization
------------

Since we all love L10n, let's see what it looks like in Jinja templates::

    <h2>{{ _('Reviews for {0}')|f(addon.name) }}</h2>

The simple way is to use the familiar underscore and string within a ``{{ }}``
moustache block.  ``f`` is an interpolation filter documented below.  Sphinx
could create a link if I knew how to do that.

The other method uses Jinja's ``trans`` tag::

        {% trans user=review.user|user_link, date=review.created|datetime %}
          by {{ user }} on {{ date }}
        {% endtrans %}

``trans`` is nice when you have a lot of text or want to inject some variables
directly.  Both methods are useful, pick the one that makes you happy.


Rendering
---------

At this point, Jingo only provides two shortcuts for rendering templates.

.. autofunction:: jingo.render

    The basic usage is to pass an ``HttpRequest`` and a template name.  All the
    processors in ``settings.CONTEXT_PROCESSORS`` will be applied to the
    context, just like when you use a ``RequestContext`` in Django.  Any extra
    keyword arguments are passed directly to ``http.HttpResponse``.


Template filters provided by jingo
----------------------------------

These filters are injected into all templates automatically.  Template filters
are what Jinja uses instead of "helpers" in other systems.  They're just
functions that get called from templates using the ``|`` (pipe) syntax.

.. automodule:: jingo.helpers
    :members:
