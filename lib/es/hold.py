from threading import local

import signals

_locals = local()


# This is heavily based on https://github.com/mozilla/kitsune/commit/85936b
# With a few tweaks.
def setup():
    # Add in the tasks object. Will return True if it was created.
    if not hasattr(_locals, 'tasks'):
        _locals.tasks = set()
        return True


def add(fun, pk):
    # By using a set, we ensure that the pk is only added once per func.
    setup()
    _locals.tasks.add((fun, pk))


def reset(**kwargs):
    setup()
    _locals.tasks.clear()


def process(**kwargs):
    # This will uniquify the tasks even more so that we only call each
    # index method once, for all the ids added to the list.
    #
    # This requires there to be a uniquely named index method that uses
    # this holding system.
    if setup():
        return

    uniq = {}
    for fun, pk in _locals.tasks:
        uniq.setdefault(fun.__name__, {'func': fun, 'ids': []})
        uniq[fun.__name__]['ids'].append(pk)

    for v in uniq.values():
        v['func'](v['ids'])

    _locals.tasks.clear()


signals.reset.connect(reset, dispatch_uid='reset_es_tasks')
signals.process.connect(process, dispatch_uid='process_es_tasks')
