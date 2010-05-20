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

``LOG_FILTERS``
    If this optional setting is set to a tuple, only log items matching strings
    in said tuple will be displayed.

    For example::

        LOG_FILTERS = ('z.sphinx.', )

    This will show you messages **only** that start with ``z.sphinx``.

``LOG_FORMAT``
    This string controls what gets printed out for each log message.  See the
    default in ``log_settings.py``.  The complete list of formatting options is
    available at http://docs.python.org/library/logging.html#formatter.

``SYSLOG_FORMAT``
    This setting is the same as ``LOG_FORMAT`` except it controls the format for
    what is sent to syslog.  By default, it's the same as ``LOG_FORMAT`` except
    it strips the date/time prefix since syslogd is going to timestamp
    everything anyway.


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

Complete logging docs: http://docs.python.org/library/logging.html
