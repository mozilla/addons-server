import logging

from django.core.management.base import BaseCommand
from django.core import mail
from django.utils import encoding

import jingo

from amo.utils import chunked

log = logging.getLogger('z.mailer')


class Command(BaseCommand):
    args = '[no really]'
    help = "Send the email for bug 574277, but only with the args 'no really'"

    def handle(self, *args, **options):
        backend = None
        if ' '.join(args) != 'no really':
            backend = 'django.core.mail.backends.console.EmailBackend'
        log.info('Using email backend: %r' % (backend or 'default'))
        cxn = mail.get_connection(backend=backend)
        sendmail(cxn)


def sendmail(cxn):
    from bandwagon.models import Collection, CollectionUser
    owners = set(Collection.objects.values_list('author', flat=True))

    # Grab all the publishers now instead of doing one query per email.
    publishers, published = {}, {}
    pubs = dict((c.id, c) for c in
                 Collection.objects.filter(users__id__isnull=False))
    for cu in CollectionUser.objects.select_related('user'):
        publishers.setdefault(cu.collection_id, []).append(cu.user)
        published.setdefault(cu.user_id, []).append(pubs[cu.collection_id])

    ids = owners | set(published)
    log.info('We have %s emails to send.' % len(ids))

    for chunk in chunked(list(ids), 300):
        send_to_ids(chunk, published, publishers, cxn)


SUBJECT = 'New features and changes to your add-on collections'
FROM = 'Mozilla Add-ons <nobody@mozilla.org>'
counter = 0
def send_to_ids(ids, published, publishers, cxn):
    from bandwagon.models import Collection
    global counter
    qs = Collection.uncached.select_related('user')
    users = {}
    for c in qs.filter(author__in=ids):
        users.setdefault(c.author, []).append(c)

    for user, cs in users.items():
        cs.extend(published.get(user.id, []))
        try:
            msg = fmt(cs, publishers)
            mail.send_mail(SUBJECT, msg, FROM, [user.email], connection=cxn)
            log.info('%s. sent to %s' % (counter, user.id))
        except Exception, e:
            log.info('%s. FAIL: (%s) %s' % (counter, user.id, e))
        counter += 1


def fmt(collections, publishers):
    return blahblah % template.render(locals())


# The template looks weird to get email whitespace right.
jingo.env.autoescape = False
template = jingo.env.from_string(u"""\
{% macro user(u) %}
{{ u.name }} {{ u.get_url_path()|absolutify }}
{% endmacro %}
{% for collection in collections %}
* {{ collection.name }}
** Owner: {{ user(collection.author) }}{% for pub in publishers[collection.id] -%}** Contributor: {{ user(pub) }}{%- endfor %}
** Current URL: {{ ('/collection/' + collection.url_slug)|absolutify }}
** New URL: {{ collection.get_url_path()|absolutify }}
{% if not loop.last %}

{% endif %}
{% endfor %}
""")


blahblah = u"""\
Dear collection owner,

We're excited to announce that a number of new features involving collections
are now live on the Mozilla Add-ons website. You can read more about these
changes on our blog:
http://blog.mozilla.com/addons/2010/09/03/new-collection-features-have-arrived

As part of these new features, we've made some changes to the way your
collections work that will affect how it is accessed and managed.

Collections will now primarily be associated with only one user. If multiple
people have access to manage your collection, only one owner will remain and
all other users will have their access level reduced to Contributor.

Collections will also get new URLs based on the single owner's username. Old
URLs will still work for a while, but the new URLs should be used when linking
to your collection.

The following is a list of your collections and who the owner will be after
these changes take place, along with the new URL:

%s
If you have any questions, please see our collection migration FAQ:
http://blog.mozilla.com/addons/collections-faq/

Thanks for creating a collection and sharing add-ons!

The Mozilla Add-ons Team

---
You are receiving this email because you manage a collection on addons.mozilla.org.
"""
