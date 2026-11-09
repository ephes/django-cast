"""Drop the unused generic ``File`` model.

The model had no views, API or templates; it was reachable only through the
Django admin. Dropping the table would silently orphan uploads under
``cast_files/``, so the migration refuses to run while any row exists. Back up
those files, delete the rows (``DELETE FROM cast_file``), then migrate again.
"""

from django.db import migrations


def refuse_if_files_exist(apps, schema_editor):
    File = apps.get_model("cast", "File")
    count = File.objects.using(schema_editor.connection.alias).count()
    if count:
        raise RuntimeError(
            f"cast.File still has {count} row(s). The File model is removed in this release: back up the "
            "referenced uploads under cast_files/, delete the rows (DELETE FROM cast_file), then migrate again."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("cast", "0089_alter_file_original"),
    ]

    operations = [
        migrations.RunPython(refuse_if_files_exist, migrations.RunPython.noop),
        migrations.DeleteModel(
            name="File",
        ),
    ]
