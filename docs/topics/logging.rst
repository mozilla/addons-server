.. _logging:

=======
Logging
=======

Logging is fun.  We all want to be lumberjacks.  My muscle-memory wants to put
``print`` statements everywhere, but it's better to use ``log.debug`` instead.
``print`` statements make mod_wsgi sad, and they're not much use in production.
Plus, ``django-debug-toolbar`` can hijack the logger and show all the log
statements generated during the last request.  When ``DEBUG = True``, all logs
will be printed to the development console where you started the server.  In
production, we're piping everything into ``syslog``.


Configuration
-------------

The root logger is set up from ``log_settings.py`` in the base of zamboni's
tree.  It sets up sensible defaults, but you can twiddle with these settings:

``LOG_LEVEL``
    This setting is required, and defaults to ``loggging.DEBUG``, which will let
    just about anything pass through.  To reconfigure, import logging in your
    settings file and pick a different level::

        import logging
        LOG_LEVEL = logging.WARN

``HAS_SYSLOG``
    Set this to ``False`` if you don't want logging sent to syslog when
    ``DEBUG`` is ``False``.

``LOGGING``
    See PEP 391 and log_settings.py for formatting help.  Each section of LOGGING
    will get merged into the corresponding section of log_settings.py.
    Handlers and log levels are set up automatically based on LOG_LEVEL and DEBUG
    unless you set them here.  Messages will not propagate through a logger unless
    propagate: True is set.

    ::

        LOGGING = {
            'loggers': {
                'caching': {'handlers': ['null']},
            },
        }

    If you want to add more to this in ``settings_local.py``, do something like
    this::

        LOGGING['loggers'].update({
            'z.paypal': {
                'level': logging.DEBUG,
            },
            'z.sphinx': {
                'handlers': ['null'],
            },
        })


Using Loggers
-------------

The ``logging`` package uses global objects to make the same logging
configuration available to all code loaded in the interpreter.  Loggers are
created in a pseudo-namespace structure, so app-level loggers can inherit
settings from a root logger.  zamboni's root namespace is just ``"z"``, in the
interest of brevity.  In the caching package, we create a logger that inherits
the configuration by naming it ``"z.caching"``::

    import commonware.log

    log = commonware.log.getLogger('z.caching')

    log.debug("I'm in the caching package.")

Logs can be nested as much as you want.  Maintaining log namespaces is useful
because we can turn up the logging output for a particular section of zamboni
without becoming overwhelmed with logging from all other parts.


commonware.log vs. logging
~~~~~~~~~~~~~~~~~~~~~~~~~~

``commonware.log.getLogger`` should be used inside the request cycle.  It
returns a ``LoggingAdapter`` that inserts the current user's IP address into
the log message.

Complete logging docs: http://docs.python.org/library/logging.html
