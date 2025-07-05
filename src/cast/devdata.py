import json
import random
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from wagtail.images.models import Image
from wagtail.models import Site

from cast.models import Audio, Blog, Episode, Gallery, Podcast, Post, Transcript, Video


class _Auto:
    """
    Sentinel value indicating an automatic default will be used.
    """

    def __bool__(self):
        # Allow `Auto` to be used like `None` or `False` in boolean expressions
        return False


Auto: Any = _Auto()


def create_user(*, name: str = "testuser", password: str = "password") -> User:
    user = User.objects.create_user(name, password=password)
    user._password = password  # type: ignore
    group = Group.objects.get(name="Moderators")
    group.user_set.add(user)  # type: ignore
    return user


def create_site() -> Site:
    return Site.objects.first()


def create_image() -> Image:
    # This is a 1x1 black png
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00"
        b"\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc````"
        b"\x00\x00\x00\x05\x00\x01\xa5\xf6E@\x00\x00"
        b"\x00\x00IEND\xaeB`\x82"
    )
    simple_png = SimpleUploadedFile(name="test.png", content=png, content_type="image/png")
    image = Image(file=simple_png)
    image.save()
    return image


def create_gallery(*, images: list[Image] = Auto) -> Gallery:
    gallery = Gallery.objects.create()
    gallery.images.add(*images)
    return gallery


def create_blog(*, owner: User = Auto, site: Site = Auto) -> Blog:
    blog = Blog(
        title="Test Blog",
        slug="test-blog",
        owner=owner or create_user(),
    )
    if not site:  # pragma: no cover
        site = create_site()
    site.root_page.add_child(instance=blog)
    return blog


def create_podcast(*, owner: User = Auto, site: Site = Auto) -> Blog:
    podcast = Podcast(
        title="Test Podcast",
        slug="test-podcast",
        owner=owner or create_user(),
    )
    if not site:  # pragma: no cover
        site = create_site()
    site.root_page.add_child(instance=podcast)
    return podcast


Body = list[dict]


def create_python_body() -> Body:
    body = [
        {
            "type": "overview",
            "value": [
                {
                    "type": "heading",
                    "value": "in_all heading",
                }
            ],
        },
        {
            "type": "detail",
            "value": [
                {
                    "type": "heading",
                    "value": "only_in_detail heading",
                }
            ],
        },
    ]
    return body


def create_post(*, blog: Blog = Auto, body: str = Auto, num: int = 1) -> Post:
    if not blog:  # pragma: no cover
        blog = create_blog()
    post = Post(
        title="Test Post",
        slug=f"test-post-{num}",
        owner=blog.owner,
        body=body or json.dumps(create_python_body()),
    )
    blog.add_child(instance=post)
    return post


def create_episode(*, blog: Blog = Auto, body: str = Auto, num: int = 1, podcast_audio: Auto) -> Episode:
    if not blog:  # pragma: no cover
        blog = create_podcast()
    if not podcast_audio:  # pragma: no cover
        podcast_audio = create_audio()
    episode = Episode(
        title="Test Episode",
        slug=f"test-episode-{num}",
        owner=blog.owner,
        podcast_audio=podcast_audio,
        body=body or json.dumps(create_python_body()),
    )
    blog.add_child(instance=episode)
    return episode


def add_image_to_body(*, body: Body, image: Image = Auto) -> Body:
    if not image:  # pragma: no cover
        image = create_image()
    body[0]["value"].append({"type": "image", "value": image.pk})
    return body


def add_gallery_to_body(*, body: Body, gallery: Gallery = Auto) -> Body:
    if not gallery:  # pragma: no cover
        gallery = create_gallery()
    images = gallery.images.all()  # type: ignore
    image_items = []
    for image in images:
        image_items.append({"id": str(uuid4()), "type": "item", "value": image.pk})
    gallery_with_layout = {"layout": "default", "gallery": image_items}
    body[0]["value"].append({"id": str(uuid4()), "type": "gallery", "value": gallery_with_layout})
    return body


def get_tests_fixture_dir() -> Path:
    return Path(__file__).parent.parent.parent / "tests" / "fixtures"


def create_mp4_file(*, fixture_dir: Path = Auto) -> SimpleUploadedFile:
    if not fixture_dir:  # pragma: no cover
        fixture_dir = get_tests_fixture_dir()
    with (fixture_dir / "test.mp4").open("rb") as f:
        mp4 = f.read()
    simple_mp4 = SimpleUploadedFile(name="test.mp4", content=mp4, content_type="video/mp4")
    return simple_mp4


def create_video(mp4_file: SimpleUploadedFile = Auto, user: User = Auto) -> Video:
    if not user:  # pragma: no cover
        user = create_user()
    if not mp4_file:  # pragma: no cover
        mp4_file = create_mp4_file()
    video = Video(title="Test Video", user=user, original=mp4_file)
    video.save(poster=False)
    return video


def add_video_to_body(*, body: Body, video: Video = Auto) -> Body:
    if not video:  # pragma: no cover
        video = create_video()
    body[0]["value"].append({"type": "video", "value": video.id})
    return body


def create_minimal_mp3():
    mp3 = (
        b"\xff\xe3\x18\xc4\x00\x00\x00\x03H\x00\x00\x00\x00"
        b"LAME3.98.2\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    )
    return mp3


def create_mp3_file() -> SimpleUploadedFile:
    mp3 = create_minimal_mp3()
    simple_mp3 = SimpleUploadedFile(name="test.mp3", content=mp3, content_type="audio/mpeg")
    return simple_mp3


def create_audio(*, mp3_file: SimpleUploadedFile = Auto, user: User = Auto) -> Audio:
    if not user:  # pragma: no cover
        user = create_user()
    if not mp3_file:  # pragma: no cover
        mp3_file = create_mp3_file()
    audio = Audio(user=user, mp3=mp3_file, title="Test Audio")
    audio.save(duration=False, cache_file_sizes=False)
    return audio


def create_transcript(*, audio: Audio = Auto, podlove: dict = Auto, vtt: str = Auto, dote: dict = Auto) -> Transcript:
    if not audio:
        audio = create_audio()
    transcript = Transcript.objects.create(audio=audio)
    if podlove:
        podlove_content = json.dumps(podlove, indent=2)
        transcript.podlove.save("podlove.json", ContentFile(podlove_content))
        transcript.save()
    if vtt:
        transcript.vtt.save("test.vtt", ContentFile(vtt))
        transcript.save()
    if dote:
        dote_content = json.dumps(dote, indent=2)
        transcript.dote.save("dote.json", ContentFile(dote_content))
        transcript.save()

    return transcript


def add_audio_to_body(*, body: Body, audio: Audio = Auto):
    if not audio:  # pragma: no cover
        audio = create_audio()
    body[0]["value"].append({"type": "audio", "value": audio.id})
    return body


def generate_blog_with_media(*, number_of_posts: int = 1, media_numbers: dict[str, int] = Auto, podcast=False) -> Blog:
    if not media_numbers:  # pragma: no cover
        media_numbers = {k: 1 for k in ["images", "videos", "audios", "galleries"]}
    blog = create_podcast() if podcast else create_blog()
    body = deepcopy(create_python_body())

    # images
    images = [create_image() for _ in range(media_numbers.get("images", 0))]
    for image in images:
        body = add_image_to_body(body=body, image=image)

    # galleries
    images = [create_image() for _ in range(media_numbers.get("images_in_galleries", 1))]
    galleries = [create_gallery(images=images) for _ in range(media_numbers.get("galleries", 0))]
    for gallery in galleries:
        body = add_gallery_to_body(body=body, gallery=gallery)

    # videos
    mp4_file = create_mp4_file()
    videos = [create_video(mp4_file=mp4_file, user=blog.owner) for _ in range(media_numbers.get("videos", 0))]
    for video in videos:
        body = add_video_to_body(body=body, video=video)

    # audios
    mp3_file = create_mp3_file()
    audios = [create_audio(mp3_file=mp3_file, user=blog.owner) for _ in range(media_numbers.get("audios", 0))]
    for audio in audios:
        body = add_audio_to_body(body=body, audio=audio)

    # transcripts
    if podcast:
        for audio in audios:
            create_transcript(audio=audio, vtt="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n\nTest transcript)")

    # serialize the body and create the posts
    serialized_body = json.dumps(body)
    for num in range(number_of_posts):
        if podcast:
            podcast_audio = random.choice(audios)
            create_episode(blog=blog, num=num, body=serialized_body, podcast_audio=podcast_audio)
        else:
            create_post(blog=blog, num=num, body=serialized_body)
    return blog
