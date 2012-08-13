import functools

from django.shortcuts import redirect


def submit_step(outer_step):
    """Wraps the function with a decorator that bounces to the right step."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(request, *args, **kw):
            from mkt.submit.views import _resume
            from mkt.submit.models import AppSubmissionChecklist
            addon = kw.get('addon', False)
            if addon:
                try:
                    step = addon.appsubmissionchecklist.get_next()
                except AppSubmissionChecklist.DoesNotExist:
                    step = None
                if step and step != outer_step:
                    return _resume(addon, step)
            return f(request, *args, **kw)
        wrapper.submitting = True
        return wrapper
    return decorator


def read_dev_agreement_required(f):
    """
    Decorator that checks if the user has read the dev agreement, redirecting
    if not.
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapper(request, *args, **kw):
            if not request.amo_user.read_dev_agreement:
                return redirect('submit.app')
            return f(request, *args, **kw)
        return wrapper
    return decorator(f)
