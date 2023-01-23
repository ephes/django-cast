# import pytest
#
# from cast import upload_handler
# from cast.models import Audio, Image, Video
#
#
# class TestUploadHandler:
#     def test_upload_handler_unknown(self, request_factory):
#         request = request_factory.post("")
#         request.FILES["original"] = "foobar.xls"
#         with pytest.raises(KeyError):
#             form_class, context = upload_handler(request)
#
#     def test_upload_handler_image(self, request_factory):
#         request = request_factory.post("")
#         for ending in ("jpg", "jpeg", "png", "gif"):
#             request.FILES["original"] = f"foobar.{ending}"
#             form_class, context = upload_handler(request)
#             assert form_class._meta.model == Image
#
#     def test_upload_handler_video(self, request_factory):
#         request = request_factory.post("")
#         for ending in ("mp4", "mov", "m4v"):
#             request.FILES["original"] = f"foobar.{ending}"
#             form_class, context = upload_handler(request)
#             assert form_class._meta.model == Video
#
#     @pytest.mark.django_db
#     def test_upload_handler_audio(self, request_factory):
#         request = request_factory.post("")
#         for ending in ("mp3", "ogg", "m4a", "opus"):
#             request.FILES["original"] = f"foobar.{ending}"
#             form_class, context = upload_handler(request)
#             assert form_class._meta.model == Audio
#
#     @pytest.mark.django_db
#     def test_upload_handler_audio_ogg(self, request_factory):
#         """For ogg the field name is different from the file ending."""
#         request = request_factory.post("")
#         request.FILES["original"] = "foobar.ogg"
#         form_class, context = upload_handler(request)
#         assert context["upload_field_name"] == "oga"
