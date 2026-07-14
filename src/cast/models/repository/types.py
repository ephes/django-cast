from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, NotRequired, Protocol, TypeAlias, TypedDict, Union

from wagtail.images.models import Image, Rendition

if TYPE_CHECKING:
    from cast.models import Audio, Post, Transcript, Video

PostByID: TypeAlias = dict[int, "Post"]
PageUrlByID: TypeAlias = dict[int, str]
HasAudioByID: TypeAlias = dict[int, bool]
AudiosByPostID: TypeAlias = dict[int, set[int]]
AudioById: TypeAlias = dict[int, "Audio"]
TranscriptByAudioId: TypeAlias = dict[int, "Transcript"]
ChaptersByAudioId: TypeAlias = dict[int, list[dict[str, str]]]
VideosByPostID: TypeAlias = dict[int, set[int]]
VideoById: TypeAlias = dict[int, "Video"]
ImagesByPostID: TypeAlias = dict[int, set[int]]
CoverURLByPostID: TypeAlias = dict[int, str]
CoverAltByPostID: TypeAlias = dict[int, str]
ImageById: TypeAlias = dict[int, Image]
RenditionsForPosts: TypeAlias = dict[int, list[Rendition]]
LinkTuples: TypeAlias = list[tuple[str, str]]
SerializedRenditions: TypeAlias = dict[int, list[dict]]

# Per-post media lookup attached to ``Post._media_lookup`` so that template-facing
# blocks can resolve audio/video/image objects without extra queries. The string
# keys are exactly ``"audio"``, ``"video"`` and ``"image"``.
MediaLookup: TypeAlias = dict[str, dict[int, Union["Audio", "Video", Image]]]

Choice: TypeAlias = tuple[str, str]


class HasChoices(Protocol):
    choices: Iterable[Choice]


class CachableBlogData(TypedDict):
    """Typed shape of the cache boundary between ``builders.py`` and ``contexts.py``.

    This is the dict produced by ``data_for_blog_cachable`` /
    ``data_for_feed_cachable`` and consumed by the ``create_from_cachable_data``
    constructors. The required keys are always written by ``add_queryset_data``;
    the ``NotRequired`` keys depend on the call path (paginated index vs. feed).

    The values are plain serialized dicts/lists (JSON-friendly), not live models.
    The TypedDict documents the *completed* boundary; it intentionally does not try
    to model the incremental construction inside the builder.
    """

    blog: dict[str, Any]
    blog_cover_image_url: str
    blog_cover_alt_text: str
    site: dict[str, Any]
    root_nav_links: LinkTuples
    template_base_dir: str
    posts: list[int]
    post_by_id: dict[int, dict[str, Any]]
    audios: dict[int, dict[str, Any]]
    videos: dict[int, dict[str, Any]]
    images: dict[int, dict[str, Any]]
    transcripts: dict[int, dict[str, Any]]
    chapters: ChaptersByAudioId
    podcast_audio_by_episode_id: dict[int, dict[str, Any]]
    renditions_for_posts: SerializedRenditions
    images_by_post_id: ImagesByPostID
    videos_by_post_id: VideosByPostID
    audios_by_post_id: AudiosByPostID
    cover_by_post_id: CoverURLByPostID
    cover_alt_by_post_id: CoverAltByPostID
    has_audio_by_id: HasAudioByID
    owner_username_by_id: dict[int, str]
    page_url_by_id: PageUrlByID
    absolute_page_url_by_id: PageUrlByID
    # Path-dependent keys:
    blog_url: NotRequired[str]
    filterset: NotRequired[dict[str, Any]]
    pagination_context: NotRequired[dict[str, Any]]
    last_build_date: NotRequired[Any]
