import pytest

# FIXME
# @pytest.mark.django_db()
# def test_post_media_sync(post, image):
#     for mtype, media in post.media_lookup.items():
#         assert len(media) == 0
#
#     # assert adding image to content adds link to m2m relation
#     post.content = "{{% image {} %}}".format(image.pk)
#     post.save()
#     assert image.pk in post.media_lookup["image"]
#
#     # assert removing image from content remvoves it from m2m relation, too
#     post.content = ""
#     post.save()
#     assert len(post.images.all()) == 0
