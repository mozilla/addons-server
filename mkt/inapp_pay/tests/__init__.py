import os


def resource(filename):
    return os.path.join(os.path.dirname(__file__),
                        'resources', filename)
