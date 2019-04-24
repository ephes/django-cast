from itertools import chain

from django.forms import Widget
from django.forms.utils import flatatt
from django.utils.http import urlencode
from django.utils.encoding import force_text
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext as _
from django.db.models.fields import BLANK_CHOICE_DASH


class DateFacetWidget(Widget):
    def __init__(self, attrs=None, choices=()):
        super().__init__(attrs)

        self.choices = choices

    def value_from_datadict(self, data, files, name):
        value = super().value_from_datadict(data, files, name)
        self.data = data
        return value

    def render(self, name, value, attrs=None, choices=(), renderer=None):
        if not hasattr(self, "data"):
            self.data = {}
        if value is None:
            value = ""
        final_attrs = self.build_attrs(self.attrs, extra_attrs=attrs)
        output = ["<div%s>" % flatatt(final_attrs)]
        options = self.render_options(choices, [value], name)
        if options:
            output.append(options)
        output.append("</div>")
        return mark_safe("\n".join(output))

    def render_options(self, choices, selected_choices, name):
        selected_choices = set(force_text(v) for v in selected_choices)
        output = []
        for option_value, option_label in chain(self.choices, choices):
            if isinstance(option_label, (list, tuple)):
                for option in option_label:
                    output.append(self.render_option(name, selected_choices, *option))
            else:
                output.append(
                    self.render_option(
                        name, selected_choices, option_value, option_label
                    )
                )
        return "\n".join(output)

    def render_option(self, name, selected_choices, option_value, option_label):
        option_value = force_text(option_value)
        if option_label == BLANK_CHOICE_DASH[0][1]:
            option_label = _("All")
        data = self.data.copy()
        data[name] = option_value
        selected = data == self.data or option_value in selected_choices
        try:
            url = data.urlencode()
        except AttributeError:
            url = urlencode(data)
        return self.option_string() % {
            "attrs": selected and ' class="selected"' or "",
            "query_string": url,
            "label": force_text(option_label),
        }

    def option_string(self):
        return '<div class="cast-date-facet-item"><a%(attrs)s href="?%(query_string)s">%(label)s</a></div>'
