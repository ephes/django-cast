from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render

from ..forms import SelectThemeForm
from ..models import get_template_base_dir
from .htmx_helpers import HtmxHttpRequest


def set_template_base_dir(request: HtmxHttpRequest, template_base_dir: str) -> None:
    """Store the template base dir in the session."""
    request.session["template_base_dir"] = template_base_dir


def select_theme(request: HtmxHttpRequest) -> HttpResponse:
    """
    Store the selected theme in the session. This is used to
    determine the template base directory for rendering the
    blog and episode pages.
    """
    template_base_dir = get_template_base_dir(request, None)
    # use the referer as the next url if it exists because request.path is
    # the url of the select theme view, and we want to redirect to the previous page
    next_url = request.headers.get("referer", request.path)
    if request.method == "POST":
        form = SelectThemeForm(request.POST)
        if form.is_valid():
            set_template_base_dir(request, form.cleaned_data["template_base_dir"])
            success_url = form.cleaned_data["next"]
            return HttpResponseRedirect(success_url)
    else:
        form = SelectThemeForm(
            initial={
                "template_base_dir": template_base_dir,
                "next": next_url,
            }
        )
    context = {
        "theme_form": form,
        "template_base_dir": template_base_dir,
        "template_base_dir_choices": form.fields["template_base_dir"].choices,  # type: ignore
        "next_url": next_url,
    }
    return render(request, f"cast/{template_base_dir}/select_theme.html", context=context)
