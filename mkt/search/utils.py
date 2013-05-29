from elasticutils.contrib.django import S as eu_S
from statsd import statsd


class S(eu_S):

    def raw(self):
        with statsd.timer('search.raw'):
            hits = super(S, self).raw()
            statsd.timing('search.took', hits['took'])
            return hits
