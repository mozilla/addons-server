import functools


def mobile_template(template):
    """
    Mark a function as mobile-ready and pass a mobile template if MOBILE.

    @mobile_template('a/{mobile/}/b.html')
    def view(request, template=None):
        ...

    if request.MOBILE=True the template will be 'a/mobile/b.html'.
    if request.MOBILE=False the template will be 'a/b.html'.

    This function is useful if the mobile view uses the same context but a
    different template.
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapper(request, *args, **kw):
            fmt = {'mobile/': 'mobile/' if request.MOBILE else ''}
            kw['template'] = template.format(**fmt)
            return f(request, *args, **kw)
        return wrapper
    return decorator


def mobilized(normal_fn):
    """
    Replace a view function with a normal and mobile view.

    def view(request):
        ...

    @mobilized(view)
    def view(request):
        ...

    The second function is the mobile version of view. The original
    function is overwritten, and the decorator will choose the correct
    function based on request.MOBILE (set in middleware).
    """
    def decorator(mobile_fn):
        @functools.wraps(mobile_fn)
        def wrapper(request, *args, **kw):
            if request.MOBILE:
                return mobile_fn(request, *args, **kw)
            else:
                return normal_fn(request, *args, **kw)
        return wrapper
    return decorator
