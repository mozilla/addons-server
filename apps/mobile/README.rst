What is this?
-------------

This library is a collection of middleware and decorators that help in creating
mobile views and directing users to the mobile version of your site.  It makes
these assumptions:

 * You can use Vary: User-Agent to serve mobile and non-mobile content through
   the same URLs.
 * You want to use separate views and/or templates for the mobile site. If
   you're building a mobile experience through media queries this library won't
   be helpful.
 * Not all views from the normal site need to be replaced with mobile views.

Setup
-----

These are the default settings::

    # A regex for detecting mobile user agents.
    MOBILE_USER_AGENTS = 'android|fennec|iemobile|iphone|opera (?:mini|mobi)'
    # The name of the cookie to set if the user prefers the mobile site.
    MOBILE_COOKIE = 'mobile'

You need these middleware (but see the User Agent caveats below)::

    MIDDLEWARE_CLASSES = (
        'mobile.middleware.DetectMobileMiddleware',
        'mobile.middleware.XMobileMiddleware',
    )


How the Mobile Site is Chosen
-----------------------------

1. The ``HTTP_USER_AGENT`` matches ``MOBILE_USER_AGENTS`` and the
   ``MOBILE_COOKIE`` is not set to ``off``.
2. *or* the ``MOBILE_COOKIE`` is set to ``on``.
3. A mobile view exists for the current URL.

The ``HTTP_USER_AGENT`` is checked against the regular expression in
``MOBILE_USER_AGENTS``. The default is a very basic set of user agents to ease
maintenance and because the cookie provides a fallback.

If ``MOBILE_COOKIE`` is set to ``on``, through ``Set-Cookie`` or through
javascript, the mobile site will be chosen regardless of the user agent. If
``MOBILE_COOKIE`` is set to ``off`` the normal site will always be chosen.


Changes to the ``request`` Object
---------------------------------

If the current request is for the mobile site, ``request.MOBILE = True``. At
all other times ``request.MOBILE = False``.


Decorators
----------

Some decorators are provided to assist with common idioms::

    @mobile_template('app/{mobile/}detail.html')
    def view(request, template=None):
        ...

``@mobile_template`` helps with the pattern of using the same view code and
template context, but switching to a different template for mobile. It follows
this logic::

    template = 'app/mobile/detail.html' if request.MOBILE else 'app/detail.html'

To use a completely different function for the mobile view::

    def view(request):
        ...

    @mobilized(view)
    def view(request):
        ...

In the example, the first definition of ``view`` will be used for the normal
site and the second function will be used for the mobile site. The normal and
mobile site point to the same view in ``urls.py`` and the decorator handles
choosing which view to run.


Varying on User Agent
---------------------

Since mobile users can enter the site from any normal URL, the
``DetectMobileMiddleware`` always inspects the ``User-Agent`` to see if it
matches something in ``MOBILE_USER_AGENTS``, and may redirect the browser to
the mobile site. Thus, every URL on the site should be sending ``Vary:
User-Agent`` to get proper HTTP caching. Varying on User-Agent can be
detrimental to your frontend cache scheme, so it's recommended that you move
mobile detection up the stack to a frontend proxy.

The proxy can run the logic in ``DetectMobileMiddleware`` and set
``HTTP_X_MOBILE`` (so we know whether to serve a mobile view) without varying
on user agent internally. Instead, it can vary on ``X-Mobile`` while
sending ``Vary: User-Agent`` back to the client. From the outside it looks like
the app varies on ``User-Agent`` but the proxy will only need to cache a
mobile and non-mobile version of the URL.
