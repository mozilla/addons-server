import jingo

import commonware.log

log = commonware.log.getLogger('z.ecosystem')


def landing(request):
    return jingo.render(request, 'ecosystem/landing.html')
