# Generated by Django 4.1.7 on 2023-03-18 07:47

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cast", "0044_alter_blog_template_base_dir_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="blog",
            name="template_base_dir",
            field=models.CharField(
                blank=True,
                choices=[("bootstrap4", "Bootstrap 4"), ("plain", "Just HTML")],
                default=None,
                help_text="The theme to use for this blog implemented as a template base directory. If not set, the template base directory will be determined by a site setting.",
                max_length=128,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="templatebasedirectory",
            name="name",
            field=models.CharField(
                choices=[("bootstrap4", "Bootstrap 4"), ("plain", "Just HTML")],
                default="bootstrap4",
                help_text="The theme to use for this site implemented as a template base directory. It's possible to overwrite this setting for each blog.If you want to use a custom theme, you have to create a new directory in your template directory named cast/<your-theme-name>/ and put all required templates in there.",
                max_length=128,
            ),
        ),
    ]
