import logging

from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)


class FileUploadResponseMixin:
    @staticmethod
    def get_success_url() -> None:
        return None

    def form_valid(self, form: ModelForm) -> HttpResponse:
        model = form.save(commit=False)
        super().form_valid(form)  # type: ignore
        return HttpResponse(f"{model.pk}", status=201)


class AddRequestUserMixin:
    request: HttpRequest
    user_field_name = "user"

    def form_valid(self, form: ModelForm) -> bool:
        model = form.save(commit=False)
        setattr(model, self.user_field_name, self.request.user)
        return super().form_valid(form)  # type: ignore
