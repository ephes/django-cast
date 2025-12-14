from __future__ import annotations

from crispy_forms.helper import FormHelper
from django_comments import get_form_target

from . import appsettings


class CommentFormHelper(FormHelper):
    form_tag = False
    form_id = "comment-form-ID"
    form_class = f"js-comments-form {appsettings.FORM_CSS_CLASS}"
    label_class = appsettings.LABEL_CSS_CLASS
    field_class = appsettings.FIELD_CSS_CLASS
    render_unmentioned_fields = True

    @property
    def form_action(self) -> str:
        return get_form_target()

    def __init__(self, form=None):
        super().__init__(form=form)
        if form is not None:
            self.form_id = f"comment-form-{form.target_object.pk}"
            self.attrs = {"data-object-id": form.target_object.pk}
