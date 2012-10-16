def run():
    print '--- dummy migration started'
    import sys
    print sys.path
    import django
    print django.__file__
    from django.conf import settings
    print settings.ROOT
    print '--- dummy migration done'
