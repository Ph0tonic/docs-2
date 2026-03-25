"""
Handle search setup that needs to be done at bootstrap time.
"""

import logging
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services.search_indexers import get_document_indexer
from core.tasks.search import batch_document_indexer_task

logger = logging.getLogger("docs.search.bootstrap_search")


class Command(BaseCommand):
    """Index all documents to remote search service"""

    help = __doc__

    def add_arguments(self, parser):
        """Add argument to require forcing execution when not in debug mode."""
        parser.add_argument(
            "--batch-size",
            action="store",
            dest="batch_size",
            type=int,
            default=settings.SEARCH_INDEXER_BATCH_SIZE,
            help="Indexation query batch size",
        )
        parser.add_argument(
            "--lower-time-bound",
            action="store",
            dest="lower_time_bound",
            type=datetime.fromisoformat,
            default=None,
            help="DateTime in ISO format. Only documents updated after this date will be indexed",
        )
        parser.add_argument(
            "--upper-time-bound",
            action="store",
            dest="upper_time_bound",
            type=datetime.fromisoformat,
            default=None,
            help="DateTime in ISO format. Only documents updated before this date will be indexed",
        )

    def handle(self, *args, **options):
        """Launch and log search index generation."""
        indexer = get_document_indexer()

        if not indexer:
            raise CommandError("The indexer is not enabled or properly configured.")

        batch_document_indexer_task.apply_async(
            kwargs={
                "lower_time_bound": options["lower_time_bound"],
                "upper_time_bound": options["upper_time_bound"],
                "batch_size": options["batch_size"],
                "crash_safe_mode": True,
            },
        )

        logger.info(
            "Document indexing task sent to worker",
        )
