from django.db import connection
from django.db import models
from django.db.models.query import ModelIterable

from caching.base import CachingModelIterable


"""
Copyright (c) 2010, Simon Willison.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

    1. Redistributions of source code must retain the above copyright notice,
       this list of conditions and the following disclaimer.

    2. Redistributions in binary form must reproduce the above copyright
       notice, this list of conditions and the following disclaimer in the
       documentation and/or other materials provided with the distribution.

    3. Neither the name of Django nor the names of its contributors may be used
       to endorse or promote products derived from this software without
       specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""


class TransformQuerySetMixin(object):
    def __init__(self, *args, **kwargs):
        super(TransformQuerySetMixin, self).__init__(*args, **kwargs)
        print('Initializing TransformQuerySetMixin (calling __init__)')
        self._transform_fns = []

    def _clone(self, **kwargs):
        clone = super(TransformQuerySetMixin, self)._clone(**kwargs)
        clone._transform_fns = self._transform_fns[:]
        return clone

    def transform(self, fn):
        clone = self._clone()

        print('append transform', fn)
        if fn not in clone._transform_fns:
            clone._transform_fns.append(fn)
        return clone

    def _fetch_all(self):
        print('calling TransformQuerySetMixin._fetch_all', 'result cache is None', self._result_cache is None)

        transform_results = (
            self._iterable_class in (ModelIterable, CachingModelIterable) and
            self._transform_fns and
            self._result_cache is None
        )

        print('calling super() _fetch_all inside TransformQuerySetMixin._fetch_all')

        if self._result_cache is None:
            self._result_cache = list(self._iterable_class(self))

        if self._prefetch_related_lookups and not self._prefetch_done:
            self._prefetch_related_objects()

        print('called super() _fetch_all inside TransformQuerySetMixin._fetch_all')

        print('Should we transform results?', transform_results, '(based on iterable_class, and if there are transform_fns)')

        if transform_results:
            print('iterate through _transform_fns')
            for fn in self._transform_fns:
                print('query count (before):', len(connection.queries))
                print('calling', fn)
                fn(self._result_cache)
                print('query count (after):', len(connection.queries))
