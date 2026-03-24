"""Add encryption_public_key_fingerprint to BaseAccess (DocumentAccess).

Stores the fingerprint of the user's public key at the time of sharing,
allowing the frontend to detect key changes without relying solely on
client-side TOFU. If the user's current key fingerprint differs from
this stored value, the document access needs re-encryption.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0029_document_is_encrypted_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentaccess",
            name="encryption_public_key_fingerprint",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Fingerprint of the user's public key at the time of sharing. "
                    "Used to detect key changes — if the user's current public key "
                    "fingerprint differs from this value, the access needs re-encryption."
                ),
                max_length=16,
                null=True,
                verbose_name="encryption public key fingerprint",
            ),
        ),
    ]
