.. _mobile:

==========================
Working on the Mobile Site
==========================

The mobile version of amo expects to be served through ``MOBILE_DOMAIN`` (the
normal site is served through ``DOMAIN``).


Defining domains
----------------

In ``etc/hosts`` I have localhost (``127.0.0.1``) aliased to ``z`` for brevity. Then
I added another ``mz`` alias for the mobile domain::

    127.0.0.1   localhost z mz

I let zamboni know about all this in ``settings_local.py``::

    DOMAIN = 'z'
    SITE_URL = 'http://%s' % DOMAIN
    MOBILE_DOMAIN = 'mz'
    MOBILE_SITE_URL = 'http://%s' % MOBILE_DOMAIN

Add ``DetectMobileMiddleware`` to your ``settings_local.py``::


    mwc = MIDDLEWARE_CLASSES
    xmobile = mwc.index('amo.middleware.XMobileMiddleware')
    detect = ('amo.middleware.DetectMobileMiddleware',)
    MIDDLEWARE_CLASSES = mwc[:xmobile] + detect + mwc[xmobile:]
