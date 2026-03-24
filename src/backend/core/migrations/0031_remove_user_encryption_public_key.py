"""Remove encryption_public_key from User model.

Public keys are now managed by the centralized encryption service.
Products should fetch public keys from the encryption service's API
when needed (e.g. for encrypting a document for multiple users).

The fingerprint of the public key at share time is stored on
DocumentAccess.encryption_public_key_fingerprint (added in 0030).
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0030_baseaccess_encryption_public_key_fingerprint"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="encryption_public_key",
        ),
    ]
