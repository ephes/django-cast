"""Shared implementation for the Wagtail-admin media CRUD/chooser views (audio, video, transcript).

Extracted from the previously triplicated per-type modules (architecture review H4).
"""

import hashlib
import json
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, cast

from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import models, router, transaction
from django.forms import ModelForm
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.vary import vary_on_headers
from modelsearch.backends.base import BaseSearchResults
from wagtail.admin import messages
from wagtail.admin.modal_workflow import render_modal_workflow
from wagtail.admin.models import popular_tags_for_model
from wagtail.search.backends import get_search_backends

from ..appsettings import CHOOSER_PAGINATION, MENU_ITEM_PAGINATION
from ..file_replacement import FileReplacementConflict, claim_row_write
from ..forms import NonEmptySearchForm
from ..media_ingest import (
    IngestPolicy,
    MediaProbeFailed,
    MediaProbeTimeout,
    MediaUploadInProgress,
    ingest_upload,
    upload_lock,
)
from . import AuthenticatedHttpRequest
from .wagtail_pagination import paginate, pagination_template

DELETE_CONFIRMATION_FIELD = "confirmation"
DELETE_CONFIRMATION_SALT = "cast.media-admin-delete"
# Seconds a reviewed delete confirmation stays usable; afterwards the editor reviews again.
DELETE_CONFIRMATION_MAX_AGE = 24 * 60 * 60
STALE_DELETE_MESSAGE = _(
    "This item changed since you opened the confirmation, or the confirmation expired. "
    "Review the current item below before deleting it."
)


def reindex(obj: Any) -> None:
    for backend in get_search_backends():
        backend.add(obj)


def delete_revision(obj: Any, user: Any) -> str:
    """Digest of the reviewed media generation: every stored column, including file names.

    The database alias is deliberately left out: the confirmation page may be read from
    a replica while the deletion compares the row loaded from the write database.
    """
    evidence = {
        "model": obj._meta.label,
        "user": user.pk,
        "fields": {field.attname: field.value_to_string(obj) for field in obj._meta.concrete_fields},
    }
    return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()


def sign_delete_confirmation(obj: Any, user: Any) -> str:
    return signing.dumps(delete_revision(obj, user), salt=DELETE_CONFIRMATION_SALT)


def delete_confirmation_matches(obj: Any, user: Any, token: str) -> bool:
    try:
        revision = signing.loads(token, salt=DELETE_CONFIRMATION_SALT, max_age=DELETE_CONFIRMATION_MAX_AGE)
    except signing.BadSignature:  # includes SignatureExpired
        return False
    return revision == delete_revision(obj, user)


@dataclass(frozen=True)
class MediaAdminConfig:
    model: type[models.Model]
    permission_policy: Any
    get_form: Callable[[], type[ModelForm]]
    url_namespace: str
    template_dir: str
    plural_context_name: str
    singular_context_name: str
    chosen_step: str
    get_chosen_data: Callable[[Any], dict[str, Any]]
    create_instance: Callable[[Any], Any]
    search: Callable[[models.QuerySet[Any], str], tuple[models.QuerySet[Any] | BaseSearchResults, str | None]]
    ordering: str | None
    show_popular_tags: bool
    index_search_placeholder: Any
    index_fallback_placeholder: Any
    added_message: Any
    add_error_message: Any
    deleted_message: Any
    chooser_upload_error_message: Any
    message_arg: Callable[[Any], Any]
    ingest_policy: Callable[[], IngestPolicy]
    upload_in_progress_message: Any
    probe_timeout_message: Any
    probe_failed_message: Any
    prepare_queryset: Callable[[Any], Any] = field(default=lambda queryset: queryset)
    add_redirect_to_edit: bool = False
    lock_uploads: bool = False
    updated_message: Any = ""
    update_error_message: Any = ""
    file_missing_message: Any = ""
    edit_form_initial: Callable[[Any], dict[str, Any]] | None = None
    get_file_for_size: Callable[[Any], Any] = field(default=lambda obj: None)
    extra_edit_context: Callable[[HttpRequest, Any], dict[str, Any]] = field(default=lambda request, obj: {})


class MediaAdminViews:
    def __init__(self, config: MediaAdminConfig) -> None:
        self.config = config

    def _save_upload(
        self,
        request: AuthenticatedHttpRequest,
        form_class: Any,
        *,
        obj: Any | None = None,
        prefix: str | None = None,
    ) -> tuple[Any, Any, bool]:
        config = self.config
        form = None
        try:
            lock = upload_lock(request.user) if config.lock_uploads and request.FILES else nullcontext()
            with lock:
                if obj is None:
                    obj = config.create_instance(request.user)
                form_kwargs = {"instance": obj, "user": request.user}
                if prefix is not None:
                    form_kwargs["prefix"] = prefix
                form = form_class(request.POST, request.FILES, **form_kwargs)
                if not form.is_valid():
                    return obj, form, False
                obj = ingest_upload(form, policy=config.ingest_policy())
                return obj, form, True
        except (MediaUploadInProgress, MediaProbeTimeout, MediaProbeFailed, FileReplacementConflict) as exc:
            if form is None:
                if obj is None:
                    obj = config.create_instance(request.user)
                form_kwargs = {"instance": obj, "user": request.user}
                if prefix is not None:
                    form_kwargs["prefix"] = prefix
                form = form_class(request.POST, request.FILES, **form_kwargs)
                form.is_valid()
            if isinstance(exc, MediaUploadInProgress):
                message = config.upload_in_progress_message
            elif isinstance(exc, FileReplacementConflict):
                message = _("Media changed while editing; reload before replacing files.")
            elif isinstance(exc, MediaProbeTimeout):
                message = config.probe_timeout_message
            else:
                message = config.probe_failed_message
            form.add_error(None, message)
            return obj, form, False

    @vary_on_headers("X-Requested-With")
    def index(self, request: HttpRequest) -> HttpResponse:
        config = self.config
        user_can_add = config.permission_policy.user_has_permission(request.user, "add")
        base_items = config.permission_policy.instances_user_has_any_permission_for(request.user, ["change", "delete"])
        base_items = config.prepare_queryset(base_items)
        if config.ordering is not None:
            base_items = base_items.order_by(config.ordering)
        if not user_can_add and not base_items.exists():
            raise PermissionDenied
        items: models.QuerySet[Any] | BaseSearchResults = base_items

        query_string = None
        if "q" in request.GET:
            form = NonEmptySearchForm(request.GET, placeholder=config.index_search_placeholder)
            if form.is_valid():
                raw_query_string = form.cleaned_data["q"]
                items, query_string = config.search(base_items, raw_query_string)
        else:
            form = NonEmptySearchForm(placeholder=config.index_fallback_placeholder)

        _paginator, item_page = paginate(request, items, per_page=MENU_ITEM_PAGINATION)

        context = {
            config.plural_context_name: item_page,
            "query_string": query_string,
            "is_searching": bool(query_string),
        }
        if config.ordering is not None:
            context["ordering"] = config.ordering

        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return render(request, f"{config.template_dir}/results.html", context)

        context.update(
            {
                "search_form": form,
                "user_can_add": user_can_add,
                "collections": None,
                "current_collection": None,
            }
        )
        if config.show_popular_tags:
            context["popular_tags"] = popular_tags_for_model(config.model)
        return render(request, f"{config.template_dir}/index.html", context)

    def add(self, request: AuthenticatedHttpRequest, *, initial: dict[str, Any] | None = None) -> HttpResponse:
        config = self.config
        if not config.permission_policy.user_has_permission(request.user, "add"):
            raise PermissionDenied
        form_class = cast(Any, config.get_form())
        if request.POST:
            obj, form, saved = self._save_upload(request, form_class)
            if saved:
                reindex(obj)

                messages.success(
                    request,
                    config.added_message.format(config.message_arg(obj)),
                    buttons=[messages.button(reverse(f"{config.url_namespace}:edit", args=(obj.id,)), _("Edit"))],
                )
                if config.add_redirect_to_edit:
                    return redirect(f"{config.url_namespace}:edit", obj.id)
                return redirect(f"{config.url_namespace}:index")
            else:
                messages.error(request, config.add_error_message.format(config.message_arg(obj)))
        else:
            obj = config.create_instance(request.user)
            form = form_class(user=request.user, instance=obj, initial=initial)

        return render(
            request,
            f"{config.template_dir}/add.html",
            {"form": form},
        )

    def edit(self, request: AuthenticatedHttpRequest, obj_id: int) -> HttpResponse:
        config = self.config
        form_class = cast(Any, config.get_form())
        obj = get_object_or_404(
            config.permission_policy.instances_user_has_permission_for(request.user, "change"),
            id=obj_id,
        )

        if request.method == "POST":
            obj, form, saved = self._save_upload(request, form_class, obj=obj)
            if saved:
                reindex(obj)

                messages.success(
                    request,
                    config.updated_message.format(config.message_arg(obj)),
                    buttons=[messages.button(reverse(f"{config.url_namespace}:edit", args=(obj.id,)), _("Edit"))],
                )
                return redirect(f"{config.url_namespace}:index")
            else:
                messages.error(request, config.update_error_message)
        elif config.edit_form_initial is not None:
            form = form_class(instance=obj, user=request.user, initial=config.edit_form_initial(obj))
        else:
            form = form_class(instance=obj, user=request.user)

        filesize = None
        media_file = config.get_file_for_size(obj)
        if media_file:
            try:
                filesize = media_file.size
            except OSError:
                pass

        if not filesize:
            messages.error(
                request,
                config.file_missing_message,
                buttons=[messages.button(reverse(f"{config.url_namespace}:delete", args=(obj.id,)), _("Delete"))],
            )

        context = {
            config.singular_context_name: obj,
            "filesize": filesize,
            "form": form,
            "user_can_delete": config.permission_policy.user_has_permission_for_instance(request.user, "delete", obj),
        }
        context.update(config.extra_edit_context(request, obj))
        return render(request, f"{config.template_dir}/edit.html", context)

    def delete(self, request: HttpRequest, obj_id: int) -> HttpResponse:
        config = self.config
        obj = get_object_or_404(
            config.permission_policy.instances_user_has_permission_for(request.user, "delete"),
            id=obj_id,
        )

        if request.method == "POST":
            token = request.POST.get(DELETE_CONFIRMATION_FIELD, "")
            using = router.db_for_write(config.model, instance=obj)
            with transaction.atomic(using=using):
                # Claim the row before reading the current generation, so a concurrent
                # replacement either commits first (and is compared) or waits for us.
                claim_row_write(config.model, obj.pk, using=using)
                current = (
                    config.permission_policy.instances_user_has_permission_for(request.user, "delete")
                    .using(using)
                    .filter(pk=obj.pk)
                    .first()
                )
                if current is None:
                    raise Http404
                confirmed = delete_confirmation_matches(current, request.user, token)
                if confirmed:
                    current.delete()
            if confirmed:
                messages.success(request, config.deleted_message.format(config.message_arg(current)))
                return redirect(f"{config.url_namespace}:index")
            messages.error(request, STALE_DELETE_MESSAGE)
            return self._render_delete_confirmation(request, current, status=409)

        return self._render_delete_confirmation(request, obj)

    def _render_delete_confirmation(self, request: HttpRequest, obj: Any, *, status: int = 200) -> HttpResponse:
        config = self.config
        context = {
            config.singular_context_name: obj,
            "delete_confirmation": sign_delete_confirmation(obj, request.user),
        }
        return render(request, f"{config.template_dir}/confirm_delete.html", context, status=status)

    def chooser(self, request: HttpRequest) -> HttpResponse:
        config = self.config
        if not config.permission_policy.user_has_permission(request.user, "choose"):
            raise PermissionDenied
        base_items = config.permission_policy.instances_user_has_permission_for(request.user, "choose")
        base_items = config.prepare_queryset(base_items)
        if config.ordering is not None:
            base_items = base_items.order_by(config.ordering)
        items: models.QuerySet[Any] | BaseSearchResults = base_items

        form_class = cast(Any, config.get_form())
        upload_form = form_class(prefix="media-chooser-upload", user=request.user)

        if "q" in request.GET or "p" in request.GET:
            search_form = NonEmptySearchForm(request.GET)
            if search_form.is_valid():
                raw_query_string = search_form.cleaned_data["q"]
                items, q = config.search(base_items, raw_query_string)
                is_searching = bool(q)
            else:
                q = None
                is_searching = False

            _paginator, item_page = paginate(request, items, per_page=CHOOSER_PAGINATION)
            return render(
                request,
                f"{config.template_dir}/chooser_results.html",
                {
                    config.plural_context_name: item_page,
                    "query_string": q,
                    "is_searching": is_searching,
                    "pagination_template": pagination_template,
                },
            )
        else:
            search_form = NonEmptySearchForm()
            _paginator, item_page = paginate(request, items, per_page=CHOOSER_PAGINATION)

        return render_modal_workflow(
            request,
            f"{config.template_dir}/chooser_chooser.html",
            None,
            {
                config.plural_context_name: item_page,
                "uploadform": upload_form,
                "searchform": search_form,
                "is_searching": False,
                "pagination_template": pagination_template,
            },
            json_data={
                "step": "chooser",
                "error_label": "Server Error",
                "error_message": "Report this error to your webmaster with the following information:",
                "tag_autocomplete_url": reverse("wagtailadmin_tag_autocomplete"),
            },
        )

    def chosen(self, request: HttpRequest, obj_id: int) -> HttpResponse:
        config = self.config
        obj = get_object_or_404(
            config.permission_policy.instances_user_has_permission_for(request.user, "choose"),
            id=obj_id,
        )

        return render_modal_workflow(
            request,
            None,
            None,
            None,
            json_data={"step": config.chosen_step, "result": config.get_chosen_data(obj)},
        )

    def chooser_upload(self, request: AuthenticatedHttpRequest) -> HttpResponse:
        config = self.config
        if not config.permission_policy.user_has_permission(
            request.user, "add"
        ) or not config.permission_policy.user_has_permission(request.user, "choose"):
            raise PermissionDenied
        form_class = cast(Any, config.get_form())
        form = None

        if request.method == "POST":
            obj, form, saved = self._save_upload(
                request,
                form_class,
                prefix="media-chooser-upload",
            )

            if saved:
                reindex(obj)

                return render_modal_workflow(
                    request,
                    None,
                    None,
                    None,
                    json_data={"step": config.chosen_step, "result": config.get_chosen_data(obj)},
                )
            else:
                messages.error(request, config.chooser_upload_error_message)

        items = config.permission_policy.instances_user_has_permission_for(request.user, "choose")
        if config.ordering is not None:
            items = items.order_by(config.ordering)

        search_form = NonEmptySearchForm()

        _paginator, item_page = paginate(request, items, per_page=CHOOSER_PAGINATION)

        context = {
            config.plural_context_name: item_page,
            "searchform": search_form,
            "uploadform": form or form_class(user=request.user),
            "is_searching": False,
            "pagination_template": pagination_template,
        }
        return render_modal_workflow(
            request,
            f"{config.template_dir}/chooser_chooser.html",
            None,
            context,
            json_data={"step": "chooser"},
        )
