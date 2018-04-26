from django.db import models
from django.db.models.query import ModelIterable


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


class TransformIterable(ModelIterable):
    def __iter__(self):
        result_iter = super(TransformIterable, self).__iter__
        self.transform_functions = self.queryset._transform_fns
        if self.transform_functions:
            # FIXME: we could pass self.queryset.db to the transform function,
            # it would allow it to use the same database, which is something
            # we've wanted to do for translations for quite some time.
            results = list(result_iter)
            for fn in self._transform_fns:
                fn(results)
            return iter(results)
        return result_iter


class TransformQuerySet(models.query.QuerySet):
    def __init__(self, *args, **kwargs):
        super(TransformQuerySet, self).__init__(*args, **kwargs)
        self._transform_fns = []

    def _clone(self, klass=None, setup=False, **kw):
        clone = super(TransformQuerySet, self)._clone(klass, setup, **kw)
        clone._transform_fns = self._transform_fns[:]
        return clone

    def transform(self, fn):
        clone = self._clone()
        clone._transform_fns.append(fn)
        return clone
