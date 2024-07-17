(logging)=

# Logging

Logging is fun.  We all want to be lumberjacks.  My muscle-memory wants to put
_print_ statements everywhere, but it's better to use _log.debug_ instead.
_print_ statements make mod_wsgi sad, and they're not much use in production.
Plus, _django-debug-toolbar_ can hijack the logger and show all the log
statements generated during the last request.  When `DEBUG = True`, all logs
will be printed to the development console where you started the server.  In
production, we're piping everything into `mozlog`.

## Configuration

The root logger is set up from _settings_base_ in the _src/olympia/lib_
of addons-server. It sets up sensible defaults, but you can tweak them to your liking:

### Log level

There is no unified log level, instead every logger has it's own log level
because it depends on the context they're used in.

### LOGGING

See PEP 391 for formatting help. Messages will not propagate through a
logger unless _propagate: True_ is set.

> ```
> LOGGING = {
>     'loggers': {
>         'caching': {'handlers': ['null']},
>     },
> }
> ```

If you want to add more to this do something like this:

```
LOGGING['loggers'].update({
    'z.paypal': {
        'level': logging.DEBUG,
    },
    'z.es': {
        'handlers': ['null'],
    },
})
```

## Using Loggers

The _olympia.core.logger_ package uses global objects to make the same
logging configuration available to all code loaded in the interpreter.  Loggers
are created in a pseudo-namespace structure, so app-level loggers can inherit
settings from a root logger.  olympia's root namespace is just `"z"`, in the
interest of brevity.  In the caching package, we create a logger that inherits
the configuration by naming it `"z.caching"`:

```
import olympia.core.logger

log = olympia.core.logger.getLogger('z.caching')

log.debug("I'm in the caching package.")
```

Logs can be nested as much as you want.  Maintaining log namespaces is useful
because we can turn up the logging output for a particular section of olympia
without becoming overwhelmed with logging from all other parts.

### olympia.core.logging vs. logging

_olympia.core.logger.getLogger_ should be used everywhere.  It returns a
_LoggingAdapter_ that inserts the current user's IP address and username into
the log message. For code that lives outside the request-response cycle, it
will insert empty values, keeping the message formatting the same.

Complete logging docs: <http://docs.python.org/library/logging.html>
