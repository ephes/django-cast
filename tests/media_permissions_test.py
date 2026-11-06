"""Image policy lookup stays lazy and honours Wagtail's configured policy."""

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from django.urls import reverse
from wagtail import permissions as wagtail_permissions
from wagtail.images import get_image_model

from cast import media_permissions
from cast.content.media_refs import get_choosable_image


def test_image_policy_imports_do_not_use_deprecated_api():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import warnings; import wagtail; "
            "warnings.filterwarnings('error', message="
            "r'wagtail.images.permissions.permission_policy is deprecated'); "
            "import django; django.setup(); "
            "import cast.content.media_refs; import cast.api.editor.media",
        ],
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "tests.settings"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_image_policy_is_looked_up_for_current_model_on_each_call(mocker):
    registry = mocker.Mock()
    mocker.patch.dict(sys.modules, {"wagtail.permissions": SimpleNamespace(policy_registry=registry)})
    model = mocker.patch.object(media_permissions, "get_image_model")
    for _ in range(2):
        assert media_permissions.get_image_permission_policy() is registry.get_by_type.return_value
    assert registry.get_by_type.call_args_list == [mocker.call(model.return_value)] * 2


def test_image_policy_falls_back_on_wagtail_7(mocker):
    legacy_policy = object()
    mocker.patch.dict(
        sys.modules,
        {
            "wagtail.permissions": SimpleNamespace(),
            "wagtail.images.permissions": SimpleNamespace(permission_policy=legacy_policy),
        },
    )
    assert media_permissions.get_image_permission_policy() is legacy_policy


@pytest.mark.django_db
def test_image_chooser_and_editor_use_registered_policy(mocker, image, admin_user, api_client):
    admin_user.is_superuser = True
    admin_user.save()
    policy = mocker.Mock(wraps=media_permissions.get_image_permission_policy())
    registry = mocker.Mock()
    registry.get_by_type.return_value = policy
    mocker.patch.object(wagtail_permissions, "policy_registry", registry, create=True)

    assert get_choosable_image(image.pk, admin_user) == image
    policy.instances_user_has_permission_for.assert_called_once_with(admin_user, "choose")
    policy.reset_mock()

    api_client.force_authenticate(user=admin_user)
    response = api_client.get(reverse("cast:api:editor_media_images"))
    assert response.status_code == 200
    assert response.json()["results"][0]["id"] == image.pk
    policy.instances_user_has_permission_for.assert_called_once_with(admin_user, "choose")
    policy.user_has_permission_for_instance.assert_called_once_with(admin_user, "change", image)

    response = api_client.get(reverse("cast:api:editor_media_collections"), {"type": "image"})
    assert response.status_code == 200
    assert policy.collections_user_has_permission_for.call_args_list == [
        mocker.call(admin_user, "add"),
        mocker.call(admin_user, "choose"),
    ]
    assert all(call == mocker.call(get_image_model()) for call in registry.get_by_type.call_args_list)
