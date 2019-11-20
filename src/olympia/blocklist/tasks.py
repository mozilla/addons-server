from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db

from .models import MultiBlockSubmit


@task
@use_primary_db
def create_blocks_from_multi_block(multi_block_submit_id, **kw):
    obj = MultiBlockSubmit.objects.get(pk=multi_block_submit_id)
    # create the blocks from the guids in the multi_block
    obj.save_to_blocks()
