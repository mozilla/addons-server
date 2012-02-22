import functools


def submit_step(outer_step):
    """Wraps the function with a decorator that bounces to the right step."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(request, *args, **kw):
            from mkt.developers.views import _resume
            addon = kw.get('addon', False)
            if addon:
                step = addon.appsubmissionchecklist.get_next()
                if step != outer_step:
                    return _resume(addon, step)
            return f(request, *args, **kw)
        wrapper.submitting = True
        return wrapper
    return decorator


