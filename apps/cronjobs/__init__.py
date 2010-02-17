registered = {}


def register(f):
    """Decorator to add the function to the cronjob library."""
    registered[f.__name__] = f
    return f
