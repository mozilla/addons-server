import os
import site

# Add the zamboni dir to the python path so we can import manage which sets up
# other paths and settings.
wsgidir = os.path.dirname(__file__)
site.addsitedir(os.path.abspath(os.path.join(wsgidir, '../')))

# manage adds the `apps` and `lib` directories to the path.

class ZamboniApp:
    def __init__(self):
        self._app = self.setup_app
        self.django_app = None

    def __call__(self, env, start_response):
        return self._app(env, start_response)

    def setup_app(self, env, start_response):
        if 'SITE' in env:
            site.addsitedir(env['SITE'])

        import manage

        import django.conf
        import django.core.handlers.wsgi
        import django.core.management
        import django.utils

        # Do validate and activate translations like using `./manage.py runserver`.
        # http://blog.dscpl.com.au/2010/03/improved-wsgi-script-for-use-with.html
        utility = django.core.management.ManagementUtility()
        command = utility.fetch_command('runserver')
        command.validate()
        django.utils.translation.activate(django.conf.settings.LANGUAGE_CODE)

        # This is what mod_wsgi runs.
        self.django_app = django.core.handlers.wsgi.WSGIHandler()

        self._app = self.zamboni_app

        return self.zamboni_app(env, start_response)

    def zamboni_app(self, env, start_response):
        if 'HTTP_X_ZEUS_DL_PT' in env:
            env['SCRIPT_URL'] = env['SCRIPT_NAME'] = ''
        return self.django_app(env, start_response)


application = ZamboniApp()

# Uncomment this to figure out what's going on with the mod_wsgi environment.
# def application(env, start_response):
#     start_response('200 OK', [('Content-Type', 'text/plain')])
#     return '\n'.join('%r: %r' % item for item in sorted(env.items()))

# vim: ft=python
