"""
Unit test for `index` command.
"""

from datetime import datetime, timedelta, timezone
from operator import itemgetter
from unittest import mock

from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import transaction

import pytest

from core import factories
from core.services.search_indexers import BULK_INDEXER_CHECKPOINT, FindDocumentIndexer
from core.tests.conftest import create_document_with_updated_at


@pytest.mark.django_db
@pytest.mark.usefixtures("indexer_settings")
def test_index_without_bound_and_crash_safe_mode_disabled_success():
    """Test the command `index` that run the Find app indexer for all the available documents."""
    user = factories.UserFactory()
    indexer = FindDocumentIndexer()

    with transaction.atomic():
        doc = factories.DocumentFactory()
        empty_doc = factories.DocumentFactory(title=None, content="")
        no_title_doc = factories.DocumentFactory(title=None)

        factories.UserDocumentAccessFactory(document=doc, user=user)
        factories.UserDocumentAccessFactory(document=empty_doc, user=user)
        factories.UserDocumentAccessFactory(document=no_title_doc, user=user)

    accesses = {
        str(doc.path): {"users": [user.sub]},
        str(empty_doc.path): {"users": [user.sub]},
        str(no_title_doc.path): {"users": [user.sub]},
    }

    with mock.patch.object(FindDocumentIndexer, "push") as mock_push:
        call_command("index")

    push_call_args = [call.args[0] for call in mock_push.call_args_list]

    # called once but with a batch of docs
    mock_push.assert_called_once()

    assert sorted(push_call_args[0], key=itemgetter("id")) == sorted(
        [
            indexer.serialize_document(doc, accesses),
            indexer.serialize_document(no_title_doc, accesses),
        ],
        key=itemgetter("id"),
    )

    # crash_safe_mode deactivated -> no checkpoint stored
    assert cache.get(BULK_INDEXER_CHECKPOINT) is None


@pytest.mark.django_db
@pytest.mark.usefixtures("indexer_settings")
def test_index_with_both_bounds_and_crash_safe_mode_success():
    """Test the command `index` for all documents within time bound."""
    cache.clear()
    lower_time_bound = datetime(2024, 2, 1, tzinfo=timezone.utc)
    upper_time_bound = lower_time_bound + timedelta(days=30)

    document_too_early = create_document_with_updated_at(
        lower_time_bound - timedelta(days=10)
    )
    document_in_window_1 = create_document_with_updated_at(
        lower_time_bound + timedelta(days=5)
    )
    document_in_window_2 = create_document_with_updated_at(
        lower_time_bound + timedelta(days=15)
    )
    document_too_late = create_document_with_updated_at(
        upper_time_bound + timedelta(days=10)
    )

    with mock.patch.object(FindDocumentIndexer, "push") as mock_push:
        call_command(
            "index",
            lower_time_bound=lower_time_bound.isoformat(),
            upper_time_bound=upper_time_bound.isoformat(),
            crash_safe_mode=True,
        )
    all_push_call_args = [
        document["id"]
        for call_arg_list in mock_push.call_args_list
        for document in call_arg_list.args[0]
    ]

    # Only documents in window should be indexed
    assert str(document_too_early.id) not in all_push_call_args
    assert str(document_in_window_1.id) in all_push_call_args
    assert str(document_in_window_2.id) in all_push_call_args
    assert str(document_too_late.id) not in all_push_call_args

    # Checkpoint should be set to last indexed document's updated_at
    assert (
        cache.get(BULK_INDEXER_CHECKPOINT)
        == document_in_window_2.updated_at.isoformat()
    )


@pytest.mark.django_db
@pytest.mark.usefixtures("indexer_settings")
def test_index_with_crash_recovery():
    """Test resuming indexing from checkpoint after a crash."""
    cache.clear()
    lower_time_bound = datetime(2024, 2, 1, tzinfo=timezone.utc)
    upper_time_bound = lower_time_bound + timedelta(days=60)

    batch_size = 2
    documents = [
        # batch 0
        create_document_with_updated_at(lower_time_bound + timedelta(days=5)),
        create_document_with_updated_at(lower_time_bound + timedelta(days=10)),
        # batch 1
        create_document_with_updated_at(lower_time_bound + timedelta(days=20)),
        create_document_with_updated_at(lower_time_bound + timedelta(days=25)),
        # batch 2 - will crash here
        create_document_with_updated_at(lower_time_bound + timedelta(days=30)),
        create_document_with_updated_at(lower_time_bound + timedelta(days=35)),
        # batch 3
        create_document_with_updated_at(lower_time_bound + timedelta(days=40)),
        create_document_with_updated_at(lower_time_bound + timedelta(days=45)),
    ]

    def push_with_failure_on_batch_2(data):
        # Crash when encounters document at index 4 (batch 2 with batch_size=2)
        if str(documents[4].id) in [document["id"] for document in data]:
            raise ConnectionError("Simulated indexing error")

    # First run: simulate crash on batch 3
    with mock.patch.object(FindDocumentIndexer, "push") as mock_push:
        mock_push.side_effect = push_with_failure_on_batch_2
        call_command(
            "index",
            batch_size=batch_size,
            lower_time_bound=lower_time_bound.isoformat(),
            upper_time_bound=upper_time_bound.isoformat(),
            crash_safe_mode=True,
        )
    all_push_call_args = [
        document["id"]
        for call_arg_list in mock_push.call_args_list
        for document in call_arg_list.args[0]
    ]

    # First 2 batches should have been indexed and checkpoint saved
    checkpoint = cache.get(BULK_INDEXER_CHECKPOINT)
    assert checkpoint == documents[3].updated_at.isoformat()
    # first 2 batches should be indexed successfully
    for i in range(0, 4):
        assert str(documents[i].id) in all_push_call_args
    # next batch should have been attempted but failed
    for i in range(4, 6):
        assert str(documents[i].id) in all_push_call_args
    # last batches indexing should not have been attempted
    for i in range(6, 8):
        assert str(documents[i].id) not in all_push_call_args

    # Second run: resume from checkpoint
    with mock.patch.object(FindDocumentIndexer, "push") as mock_push:
        call_command(
            "index",
            batch_size=batch_size,
            lower_time_bound=checkpoint,
            upper_time_bound=upper_time_bound.isoformat(),
            crash_safe_mode=True,
        )
        all_push_call_args = [
            document["id"]
            for call_arg_list in mock_push.call_args_list
            for document in call_arg_list.args[0]
        ]

        # first 2 batches should NOT be re-indexed
        # except the last document of the last batch which is on the checkpoint boundary
        # -> doc 0, 1 and 2
        for i in range(0, 3):
            assert str(documents[i].id) not in all_push_call_args
        # next batches should be indexed including the document at the checkpoint boundary
        # which has already been indexed and is re-indexed
        # -> doc 3 to the end
        for i in range(3, 8):
            assert str(documents[i].id) in all_push_call_args


@pytest.mark.django_db
@pytest.mark.usefixtures("indexer_settings")
def test_index_improperly_configured(indexer_settings):
    """The command should raise an exception if the indexer is not configured"""
    indexer_settings.SEARCH_INDEXER_CLASS = None

    with pytest.raises(CommandError) as err:
        call_command("index")

    assert str(err.value) == "The indexer is not enabled or properly configured."
