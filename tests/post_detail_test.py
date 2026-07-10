import json
import re

import pytest

from cast.models import Post
from cast.models.image_renditions import (
    create_missing_renditions_for_posts,
    get_all_images_from_posts,
    get_obsolete_and_missing_rendition_strings,
)


class TestPostDetail:
    pytestmark = pytest.mark.django_db

    def test_get_post_detail(self, client, post):
        detail_url = post.get_url()

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert post.title in content
        assert f'<link rel="canonical" href="{post.full_url}">' in content
        assert '<meta name="twitter:card" content="summary">' in content
        assert f'<meta name="twitter:title" content="{post.title}">' in content
        assert f'<meta property="og:title" content="{post.title}">' in content
        assert '<meta property="article:published_time"' in content
        assert '<meta property="article:modified_time"' in content
        assert '"@type": "BlogPosting"' in content
        assert '<meta name="twitter:image"' not in content
        assert '<meta property="og:image" content="">' not in content

    def test_blog_cover_emits_large_image_metadata(self, client, post, blog, image):
        blog.cover_image = image
        blog.cover_alt_text = 'A "quoted" cover'
        blog.save()

        response = client.get(post.get_url())

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert '<meta name="twitter:card" content="summary_large_image">' in content
        assert '<meta name="twitter:image" content="http://testserver/' in content
        assert '<meta name="twitter:image:alt" content="A &quot;quoted&quot; cover">' in content
        assert "fill-1200x630" in content
        assert '<meta property="og:image:width" content="1">' in content
        assert '<meta property="og:image:height" content="1">' in content

    def test_social_metadata_escapes_html_and_json_ld(self, client, post):
        post.seo_title = 'Search "title" </script> & friends'
        post.search_description = 'Description with "quotes", <markup>, & apostrophes\'.'
        post.save()

        response = client.get(post.get_url())

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "</script> & friends" not in content
        assert "Search &quot;title&quot; &lt;/script&gt; &amp; friends" in content
        match = re.search(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', content, re.DOTALL)
        assert match is not None
        structured_data = json.loads(match.group(1))
        assert structured_data["headline"] == post.seo_title
        assert structured_data["description"] == post.search_description

    def test_plain_theme_wraps_title_and_overrides_description(self, client, post):
        post.seo_title = "Plain search title"
        post.search_description = "Plain search description."
        post.save()

        response = client.get(post.get_url(), {"template_base_dir": "plain"})

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "cast/plain/post.html" in [template.name for template in response.templates]
        assert "<title>Plain search title</title>" in content
        assert '<meta name="description" content="Plain search description.">' in content
        assert "Title of my Site!" not in content
        assert "Description of my site" not in content

    def test_post_social_metadata_prefers_promote_fields(self, client, post):
        post.seo_title = "Concise search title"
        post.search_description = "A concise search and social description."
        post.save()

        response = client.get(post.get_url())

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "<title>Concise search title</title>" in content
        assert '<meta name="twitter:title" content="Concise search title">' in content
        assert '<meta name="twitter:description" content="A concise search and social description.">' in content
        assert '<meta property="og:title" content="Concise search title">' in content
        assert '<meta property="og:description" content="A concise search and social description.">' in content
        match = re.search(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', content, re.DOTALL)
        assert match is not None
        structured_data = json.loads(match.group(1))
        assert structured_data["@type"] == "BlogPosting"
        assert structured_data["headline"] == "Concise search title"
        assert structured_data["description"] == "A concise search and social description."
        assert structured_data["url"] == post.full_url

    def test_get_post_detail_with_detail(self, client, post):
        detail_url = post.get_url()

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "in_all" in content
        assert "only_in_detail" in content

    def test_get_description_does_not_leak_template_into_later_renders(self, client, post):
        """get_description must not mutate instance state (architecture review H1)."""
        request = client.get(post.get_url()).wsgi_request
        description = post.get_description(request=request)
        assert description
        template_after = post.get_template(request)
        assert template_after.endswith("/post.html")

    def test_get_description_does_not_leak_template_into_later_renders_for_episode(self, client, episode):
        request = client.get(episode.get_url()).wsgi_request
        description = episode.get_description(request=request)
        assert description
        template_after = episode.get_template(request)
        assert template_after.endswith("/episode.html")

    def test_post_detail_with_gallery(self, client, post_with_gallery):
        create_missing_renditions_for_posts([post_with_gallery])
        images_with_type = get_all_images_from_posts([post_with_gallery])
        _, missing_renditions = get_obsolete_and_missing_rendition_strings(images_with_type)
        print("missing renditions: ", missing_renditions)
        from wagtail.images.models import Image

        for image_id, filter_specs in missing_renditions.items():
            image = Image.objects.get(id=image_id)
            print("create renditions for image: ", image.pk, filter_specs)
            foo = image.get_renditions(*filter_specs)
            for fstr, rend in foo.items():
                rend.save()
                print("fstr: ", fstr)
                print("rend: ", rend.pk)

        renditions = Post.get_all_renditions_from_queryset([post_with_gallery])
        print("all renditions: ", renditions)
        detail_url = post_with_gallery.get_url()

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "cast-gallery-thumbnail" in content
