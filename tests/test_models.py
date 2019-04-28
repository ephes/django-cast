import os
import pytest

from cast.models import Image


class TestImageModel:
    @pytest.mark.django_db
    def test_get_all_image_paths(self, image):
        all_paths = list(image.get_all_paths())
        assert len(all_paths) == len(image.IMAGE_SIZES) + 1

    @pytest.mark.django_db
    def test_get_srset(self, image):
        assert len(image.srcset.split(",")) == len(image.IMAGE_SIZES) + 1

    @pytest.mark.django_db
    def test_thumbnail_src(self, image):
        assert image.thumbnail_src.endswith("jpg")

    @pytest.mark.django_db
    def test_full_src(self, image):
        assert image.full_src.endswith("jpg")


class TestVideoModel:
    @pytest.mark.django_db
    def test_get_all_video_paths(self, video):
        all_paths = list(video.get_all_paths())
        assert len(all_paths) == 1

    @pytest.mark.django_db
    def test_get_all_video_paths_with_poster(self, video_with_poster):
        all_paths = list(video_with_poster.get_all_paths())
        assert len(all_paths) == 3

    @pytest.mark.django_db
    def test_get_all_video_paths_without_thumbnail(self, video):

        class Dummy:
            name = "foobar"
            closed = True

            def open(self):
                return None

            def close(self):
                return None

            def seek(self, position):
                return None

            def read(self, num_bytes):
                return b""

            def tell(self):
                return 0

        video.poster = Dummy()
        all_paths = list(video.get_all_paths())
        assert len(all_paths) == 2


class TestGalleryModel:
    @pytest.mark.django_db
    def test_get_image_ids(self, gallery):
        assert len(gallery.image_ids) == gallery.images.count()
