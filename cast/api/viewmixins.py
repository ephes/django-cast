import logging

from django.http import HttpResponse


logger = logging.getLogger(__name__)


class FileUploadResponseMixin:
    def get_success_url(self):
        return None

    def form_valid(self, form):
        model = form.save(commit=False)
        super().form_valid(form)
        return HttpResponse(f"{model.pk}", status=201)


class AddRequestUserMixin:
    user_field_name = "user"

    def form_valid(self, form):
        model = form.save(commit=False)
        setattr(model, self.user_field_name, self.request.user)
        return super().form_valid(form)
