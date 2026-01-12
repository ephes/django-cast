from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def format_timestamp_ms(milliseconds: int) -> str:
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"


def build_podlove_transcript(entries: int) -> dict[str, list[dict[str, Any]]]:
    transcripts = []
    current_ms = 0
    for idx in range(entries):
        next_ms = current_ms + 5000
        transcripts.append(
            {
                "start": format_timestamp_ms(current_ms),
                "start_ms": current_ms,
                "end": format_timestamp_ms(next_ms),
                "end_ms": next_ms,
                "speaker": "Speaker",
                "voice": "",
                "text": f"Transcript line {idx + 1} for performance testing.",
            }
        )
        current_ms = next_ms
    return {"transcripts": transcripts}


def get_owner():
    from django.contrib.auth import get_user_model

    from cast.devdata import create_user

    user_model = get_user_model()
    owner = user_model.objects.first()
    if owner is None:
        owner = create_user()
    return owner


def get_root_page():
    from wagtail.models import Site

    site = Site.objects.first()
    if site is None:
        raise RuntimeError("No Wagtail Site found. Run migrations and create the default site first.")
    return site.root_page


def create_podcast(slug: str, title: str):
    from wagtail.models import Page

    from cast.models import Podcast

    if Page.objects.filter(slug=slug).exists():
        raise RuntimeError(f"A page with slug '{slug}' already exists.")

    owner = get_owner()
    root = get_root_page()
    podcast = Podcast(title=title, slug=slug, owner=owner)
    root.add_child(instance=podcast)
    podcast.save_revision().publish()
    return podcast


def create_episode(*, podcast, index: int, transcript_entries: int):
    from cast.devdata import add_audio_to_body, create_audio, create_python_body, create_transcript
    from cast.models import Episode

    owner = podcast.owner
    audio = create_audio(user=owner)
    create_transcript(audio=audio, podlove=build_podlove_transcript(transcript_entries))

    body = add_audio_to_body(body=create_python_body(), audio=audio)
    episode = Episode(
        title=f"Episode {index}",
        slug=f"{podcast.slug}-episode-{index}",
        owner=owner,
        podcast_audio=audio,
        body=json.dumps(body),
    )
    podcast.add_child(instance=episode)
    episode.save_revision().publish()
    return episode


def main() -> int:
    parser = argparse.ArgumentParser(description="Create local Podlove performance data in the example site.")
    parser.add_argument("--episodes", type=int, default=5, help="Number of episodes to create.")
    parser.add_argument(
        "--transcripts",
        type=int,
        default=200,
        help="Transcript entries per episode (increase to simulate heavier payloads).",
    )
    parser.add_argument("--slug", default="show", help="Podcast slug for the list page.")
    parser.add_argument("--title", default="Performance Podcast", help="Podcast title.")
    args = parser.parse_args()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example_site.settings.dev")

    import django

    django.setup()

    try:
        podcast = create_podcast(args.slug, args.title)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    episodes = []
    for index in range(1, args.episodes + 1):
        episodes.append(create_episode(podcast=podcast, index=index, transcript_entries=args.transcripts))

    print("Created podcast and episodes for Podlove performance testing.")
    print(f"List page: {podcast.url}")
    if episodes:
        print(f"Detail page: {episodes[0].url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
