import jingo

from amo.decorators import login_required, permission_required


@login_required
@permission_required('AccountLookup', 'View')
def home(request):
    return jingo.render(request, 'acct_lookup/home.html', {})
