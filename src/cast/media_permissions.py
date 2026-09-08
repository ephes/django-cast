"""Collection permissions shared by media forms and admin views."""

from collections.abc import Iterable
from typing import Any

from django.db.models import QuerySet
from wagtail.permission_policies.collections import CollectionOwnershipPermissionPolicy, CollectionPermissionPolicy

from .models import Audio, Transcript

audio_permission_policy = CollectionOwnershipPermissionPolicy(Audio, auth_model=Audio, owner_field_name="user")


class TranscriptPermissionPolicy(CollectionPermissionPolicy):
    """Transcript admin access also requires choosing the linked Audio."""

    def instances_user_has_any_permission_for(self, user: Any, actions: Iterable[str]) -> QuerySet[Transcript]:
        return (
            super()
            .instances_user_has_any_permission_for(user, actions)
            .filter(audio__in=audio_permission_policy.instances_user_has_permission_for(user, "choose"))
        )

    def user_has_permission_for_instance(self, user: Any, action: str, instance: Transcript) -> bool:
        return self.user_has_any_permission_for_instance(user, [action], instance)

    def user_has_any_permission_for_instance(self, user: Any, actions: Iterable[str], instance: Transcript) -> bool:
        return self.instances_user_has_any_permission_for(user, actions).filter(pk=instance.pk).exists()


transcript_permission_policy = TranscriptPermissionPolicy(Transcript)
