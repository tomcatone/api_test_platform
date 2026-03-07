"""
Placeholder migration: represents the 0011 migration that exists on existing databases.
For fresh installs: no-op (all columns are handled by 0001_initial + 0002_add_mtls_fields + apps.py auto-migrate)
For existing users: this node satisfies the dependency reference in 0003_merge_migrations
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        # Meta-only changes (ordering, verbose_name) - no schema changes needed.
        # All actual column additions are handled by _auto_migrate_columns() in apps.py.
    ]
