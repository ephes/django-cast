from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol, TypeAlias

from wagtail.images.models import Image, Rendition

if TYPE_CHECKING:
    from cast.blocks import (
        AudioChooserBlock,
        GalleryBlockWithLayout,
        ImageChooserBlock,
        VideoChooserBlock,
    )
    from cast.models import Audio, Post, Transcript, Video

PostByID: TypeAlias = dict[int, "Post"]
PageUrlByID: TypeAlias = dict[int, str]
HasAudioByID: TypeAlias = dict[int, bool]
AudiosByPostID: TypeAlias = dict[int, set["Audio"]]
AudioById: TypeAlias = dict[int, "Audio"]
TranscriptByAudioId: TypeAlias = dict[int, "Transcript"]
VideosByPostID: TypeAlias = dict[int, set["Video"]]
VideoById: TypeAlias = dict[int, "Video"]
ImagesByPostID: TypeAlias = dict[int, set["Image"]]
CoverURLByPostID: TypeAlias = dict[int, str]
CoverAltByPostID: TypeAlias = dict[int, str]
ImageById: TypeAlias = dict[int, Image]
RenditionsForPosts: TypeAlias = dict[int, list[Rendition]]
LinkTuples: TypeAlias = list[tuple[str, str]]
RenditionsForPost: TypeAlias = dict[int, list[Rendition]]
SerializedRenditions: TypeAlias = dict[int, list[dict]]
if TYPE_CHECKING:
    CastBlock: TypeAlias = (
        type["AudioChooserBlock"]
        | type["VideoChooserBlock"]
        | type["ImageChooserBlock"]
        | type["GalleryBlockWithLayout"]
    )

Choice: TypeAlias = tuple[str, str]


class HasChoices(Protocol):
    choices: Iterable[Choice]
