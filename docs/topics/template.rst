.. _templates:

======================
Templating with Jinja2
======================

We use Jinja2 for out templating.  To read more, see Jingo_.  This document
will only cover specifics of how we do templating for AMO_.

Helpers
-------

Jingo_ automatically loads helpers placed in `helpers.py` in any installed app.

Context Filters
---------------
Jinja2 has a special kind of filter known as the Context Filter.  A context
filter will take as it's first argument a template context, from which
contextual data might exist.  E.g. ``context['request'].user`` will contain the
requesting ``User``.

A function can be turned into a context filter like so:

::

    @jinja2.contextfilter
    def my_filter(context, string):
        return "Hello {0}, {1}!!!".format(context['request'].user, string)

Template Files
--------------
Template files should be stored in ``apps/{APP_NAME}/templates/{APP_NAME}``
with exceptions for global template files.  Jingo_ allows us to follow standard
Django conventions for dealing with Jinja2.

Typically templates will extend ``base.html``:

::

    {% extends "base.html" %}

Pages should try to have unique titles, this can be achieved with the following
snippet:

::

    {% block title %}{{ page_title(_('My Unique Title')) }}{% endblock %}

.. _Jingo: http://jbalogh.me/projects/jingo/
.. _AMO: https://addons.mozilla.org/en-US/firefox/
