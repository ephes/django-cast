from django import forms


class PrivateClearableFileInput(forms.ClearableFileInput):
    template_name = "cast/widgets/private_clearable_file_input.html"

    def is_initial(self, value):
        return bool(value and getattr(value, "name", ""))

    def format_value(self, value):
        if self.is_initial(value):
            return value.name
        return None
