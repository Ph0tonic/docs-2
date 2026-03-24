"""Trigger document indexation using celery task."""

from logging import getLogger

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q

from django_redis.cache import RedisCache

from core import models
from core.services.search_indexers import (
    get_document_indexer,
)

from impress.celery_app import app

logger = getLogger(__file__)


@app.task
def document_indexer_task(document_id):
    """
    Celery Task: Indexes a single document by its ID.
    
    Args:
        document_id: Primary key of the document to index.
    """
    indexer = get_document_indexer()

    if indexer:
        logger.info("Start document %s indexation", document_id)
        indexer.index(models.Document.objects.filter(pk=document_id))


def batch_indexer_throttle_acquire(timeout: int = 0, atomic: bool = True):
    """
    Acquire a throttle lock to prevent multiple batch indexation tasks during countdown.
    
    implements a debouncing pattern: only the first call during the timeout period
    will succeed, subsequent calls are skipped until the timeout expires.

    Args:
        timeout (int): Lock duration in seconds (countdown period).
        atomic (bool): Use Redis locks for atomic operations if available.
    
    Returns:
        bool: True if lock acquired (first call), False if already held (subsequent calls).
    """
    key = "document-batch-indexer-throttle"

    # Redis is used as cache database (not in tests). Use the lock feature here
    # to ensure atomicity of changes to the throttle flag.
    if isinstance(cache, RedisCache) and atomic:
        with cache.locks(key):
            return batch_indexer_throttle_acquire(timeout, atomic=False)

    # cache.add() is atomic test-and-set operation:
    #   - If key doesn't exist: creates it with timeout and returns True
    #   - If key already exists: does nothing and returns False
    # The key expires after timeout seconds, releasing the lock.
    # The value 1 is irrelevant, only the key presence/absence matters.
    return cache.add(key, 1, timeout=timeout)


@app.task
def batch_document_indexer_task(timestamp):
    """
    Celery Task: Batch indexes all documents modified since timestamp.
    
    Args:
        timestamp: ISO timestamp to filter documents by updated_at, deleted_at, 
                   or ancestors_deleted_at.
    """
    indexer = get_document_indexer()

    if indexer:
        queryset = models.Document.objects.filter(
            Q(updated_at__gte=timestamp)
            | Q(deleted_at__gte=timestamp)
            | Q(ancestors_deleted_at__gte=timestamp)
        )

        count = indexer.index(queryset)
        logger.info("Indexed %d documents", count)


def trigger_batch_document_indexer(document):
    """
    Trigger document indexation with optional debounce mechanism.
    
    behavior depends on SEARCH_INDEXER_COUNTDOWN setting:
    - if countdown > 0 sec (async batch mode):
      * schedules a batch indexation task after countdown in seconds
      * uses throttle mechanism to ensure only ONE batch task runs per countdown period
      * all documents modified since first trigger are indexed together
    - if countdown == 0 sec (sync mode):
      * executes indexation synchronously in the current thread
      * no batching, no throttling, no Celery task queuing
    
    Args:
        document (Document): the document instance that triggered the indexation.
    """
    countdown = int(settings.SEARCH_INDEXER_COUNTDOWN)

    # DO NOT create a task if indexation is disabled
    if not settings.SEARCH_INDEXER_CLASS:
        return

    if countdown > 0:
        # use throttle to ensure only one task is scheduled per countdown period.
        # if throttle acquired, schedule batch task; otherwise skip.
        if batch_indexer_throttle_acquire(timeout=countdown):
            logger.info(
                "Add task for batch document indexation from updated_at=%s in %d seconds",
                document.updated_at.isoformat(),
                countdown,
            )

            batch_document_indexer_task.apply_async(
                args=[document.updated_at], countdown=countdown
            )
        else:
            logger.info("Skip task for batch document %s indexation", document.pk)
    else:
        document_indexer_task.apply(args=[document.pk])
