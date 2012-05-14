from django.db import transaction
from django.shortcuts import get_object_or_404

import json

import commonware.log

from piston.handler import BaseHandler
from piston.utils import rc

from amo.decorators import json_response
from files.models import FileUpload
from mkt.developers import tasks
from mkt.developers.forms import NewManifestForm


log = commonware.log.getLogger('z.api')


class ValidationHandler(BaseHandler):
    allowed_methods = ('GET', 'POST')
    model = FileUpload
    email_errors = False
    display_errors = False

    @transaction.commit_on_success
    def create(self, request, id=None):
        # id = None is needed because the URL mapping is going to pass it in.
        form = NewManifestForm(request.POST)
        if form.is_valid():
            upload = FileUpload.objects.create()
            tasks.fetch_manifest.delay(form.cleaned_data['manifest'],
                                       upload.pk)
            return json_response({'id': upload.pk}, status_code=202)

        else:
            errors = dict(form.errors.items())
            return json_response({'error': errors}, status_code=400)

    def read(self, request, id=None):
        upload = get_object_or_404(FileUpload, uuid=id)
        if upload.user.pk != request.amo_user.pk:
            return rc.FORBIDDEN

        res = {'processed': bool(upload.valid or upload.validation)}
        if not upload.valid and upload.validation:
            res['valid'] = False
            res['validation'] = json.loads(upload.validation)
        elif upload.valid:
            res['valid'] = True
        return json_response(res)
