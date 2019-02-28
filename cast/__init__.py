__version__ = "0.1.6"

def upload_handler(request):
    from . import models
    from filepond.forms import get_model_form

    lookup = {}
    for ending in ("jpg", "jpeg", "png", "gif"):
        lookup[ending] = (models.Image, "original", "user")

    for ending in ("wav", "webm", "ogg", "mp3", "m4a"):
        lookup[ending] = (models.Audio, ending, "user")

    for ending in ("mp4", "mov"):
        lookup[ending] = (models.Video, "original", "user")

    file_name = str(request.FILES["original"])
    ending = file_name.lower().split(".")[-1]
    print("request filename: ", file_name, ending)
    print("request user: ", request.user)
    local_model, upload_field_name, user_field = lookup[ending]
    return get_model_form(
        local_model, upload_field_name=upload_field_name, user_field=user_field
    )
