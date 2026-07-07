from typing import Any

from django import forms
from django.core.files.base import File


class PrivateClearableFileInput(forms.ClearableFileInput):
    template_name = "cast/widgets/private_clearable_file_input.html"

    def is_initial(self, value: File | str | None) -> bool:
        return bool(value and getattr(value, "name", ""))

    def format_value(self, value: Any) -> Any:
        if self.is_initial(value):
            return value.name
        return None
