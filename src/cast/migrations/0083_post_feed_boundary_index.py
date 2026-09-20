from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("cast", "0082_alter_blog_template_base_dir_and_more")]

    operations = [
        migrations.AddIndex(
            model_name="post",
            index=models.Index(fields=["visible_date", "page_ptr"], name="cast_post_feed_boundary_idx"),
        ),
    ]
