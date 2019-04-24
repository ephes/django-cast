__version__ = "0.1.19"
from pathlib import Path

default_app_config = "cast.apps.CastConfig"


def podcast_same_audio_case(audio_model, file_name, context):
    """
    podcast special case:

    Upload all audio fiels with the same name into same
    model instance, because podcast audio consists of
    different files with the same content.
    """
    stemmed_filename = Path(file_name).stem
    for audio in audio_model.objects.order_by("-created")[:10]:
        # FIXME use index instead of limit trick (maybe)
        if stemmed_filename in audio.get_audio_file_names():
            context["instance"] = audio
    return context


def upload_handler(request):
    # Apps aren't loaded yet.
    from . import models
    from filepond.forms import get_model_form

    lookup = {}
    for ending in ("jpg", "jpeg", "png", "gif"):
        lookup[ending] = (models.Image, "original", "user")

    for ending in ("wav", "webm", "ogg", "mp3", "m4a", "opus"):
        upload_field_name = ending
        if ending == "ogg":
            upload_field_name = "oga"
        lookup[ending] = (models.Audio, upload_field_name, "user")

    for ending in ("mp4", "mov", "m4v"):
        lookup[ending] = (models.Video, "original", "user")

    file_name = str(request.FILES["original"])
    ending = Path(file_name).suffix.split(".")[-1].lower()
    local_model, upload_field_name, user_field = lookup[ending]
    form_class, context = get_model_form(
        local_model, upload_field_name=upload_field_name, user_field=user_field
    )
    if local_model.__name__ == "Audio":
        context = podcast_same_audio_case(models.Audio, file_name, context)
    return form_class, context
