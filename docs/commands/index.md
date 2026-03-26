# Index Command

The `index` management command is used to index documents to the remote search indexer.

It sends an asynchronous task to the Celery worker.

## Usage

### Command line

```bash
python manage.py index \
  --lower-time-bound "2024-01-01T00:00:00" \
  --upper-time-bound "2024-01-31T23:59:59" \
  --batch-size 200 \
  --crash-safe-mode
```

### Django Admin

The command is available in the Django admin interface:

1. Go to `/admin/`
2. Click on **"Run Indexing"** in the CORE section
3. Fill in the form with the desired parameters
4. Click **"Run Indexing Command"**

### Make Command

```bash
# Basic usage with defaults
make index

# With custom parameters
make index batch_size=200 lower_time_bound="2024-01-01T00:00:00" crash_safe_mode=true

# All parameters
make index batch_size=200 \
  lower_time_bound="2024-01-01T00:00:00" \
  upper_time_bound="2024-01-31T23:59:59" \
  crash_safe_mode=true
```

## Parameters

### `--batch-size`
- **type:** Integer
- **default:** `settings.SEARCH_INDEXER_BATCH_SIZE`
- **description:** Number of documents to process per batch. Higher values may improve performance but use more memory.

### `--lower-time-bound`
- **optional**: true
- **type:** ISO 8601 datetime string
- **default:** `None`
- **description:** Only documents updated after this date will be indexed.

### `--upper-time-bound`
- **optional**: true
- **type:** ISO 8601 datetime string
- **default:** `None`
- **description:** Only documents updated before this date will be indexed.

### `--crash-safe-mode`
- **type:** Boolean flag
- **default:** `False`
- **description:** When enabled, the command orders documents by `updated_at` and stores the last indexed document's timestamp in cache. This allows resuming indexing from the last successful batch in case of a crash. However, it is more computationally expensive due to sorting.


