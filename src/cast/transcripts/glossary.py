"""Pure matching engine for the transcript glossary.

The glossary corrects names and terms that speech recognition cannot spell.
Three sources are merged per episode (see ``EffectiveGlossary``):

- contributors credited by the episode (``display_name`` plus explicit
  ``variant => replacement`` lines),
- show terms of the podcast (canonical ``term`` plus variants),
- episode terms derived from the show notes (``episode_terms``).

Listed variants are replaced automatically (``find_replacements``); everything
else is a fuzzy proposal an editor decides (``find_proposals``), grouped by the
correct spelling (``group_proposals``). Nothing here touches Django: callers
pass plain strings and segments with ``start_ms`` and ``text``.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from html.parser import HTMLParser
from importlib.resources import files
from typing import Protocol

SOURCE_CONTRIBUTOR = "contributor"
SOURCE_SHOW = "show"
SOURCE_EPISODE = "episode"
SOURCE_CONFLICT = "conflict"

SIMILARITY_THRESHOLD = 0.8
MIN_TARGET_LETTERS = 3

COMMON_WORD_LANGUAGES: tuple[str, ...] = ("de", "en")

# Supported apostrophes: ASCII, right and left single quotation marks, modifier letter apostrophe.
APOSTROPHES = "'\u2019\u2018\u02bc"
_APOSTROPHES = str.maketrans({character: "'" for character in APOSTROPHES[1:]})
_APOSTROPHE_CLASS = "[" + APOSTROPHES + "]"
_JOINER_CLASS = "[-./" + APOSTROPHES + "]"
_WHITESPACE = re.compile(r"\s+")
# A word: identifier characters (letters, digits, underscore), optionally joined by inner
# apostrophes, hyphens, dots or slashes ("John's", "O‘Brian", "Hendryx-Parker", "sixfeetup.com",
# "owner/repo", "Brian_Smith").
# Identifier characters; U+02BC is a letter to Unicode but an apostrophe here.
_WORD = r"[^\W\u02bc]"
_TOKEN = re.compile(_WORD + "+(?:" + _JOINER_CLASS + _WORD + "+)*")
_POSSESSIVE = re.compile(_APOSTROPHE_CLASS + r"s$", re.IGNORECASE)
# Phrase boundaries: never start or end inside a longer token. A trailing apostrophe with a
# possessive or contraction suffix is allowed, so the suffix is kept ("John's" -> "Jon's").
_PHRASE_START = "(?<!" + _WORD + ")(?<!" + _WORD + _JOINER_CLASS + ")"
# After an apostrophe only a possessive or contraction suffix may follow ("Al'Qaeda" is one token).
_SUFFIX_AFTER_APOSTROPHE = "(?:s|d|ll|re|ve|m|t)(?!" + _WORD + ")(?!" + _JOINER_CLASS + _WORD + ")"
_PHRASE_END = (
    "(?!"
    + _WORD
    + ")(?![-./]"
    + _WORD
    + ")(?!"
    + _APOSTROPHE_CLASS
    + "(?!"
    + _SUFFIX_AFTER_APOSTROPHE
    + ")"
    + _WORD
    + ")"
)
# Case-insensitive matching uses simple case folding; the one expanding fold that matters for
# the supported languages, ß/ẞ -> ss, is matched explicitly so "Weiß" and "weiss" are one variant.
_SHARP_S = re.compile(r"(ss|ß|ẞ)", re.IGNORECASE)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-zß-ÿ])(?=[A-ZÀ-Þ])|(?<=[A-Z])(?=[A-Z][a-z])")
_YEAR_OR_NUMBER = re.compile(r"^#?\d[\d.]*$")
_TERM_SEPARATORS = re.compile(r"\s*(?::\s|\s[-–—|]\s)\s*")
_BRACKET_NOTE = re.compile(r"\s*[\[(]([^\[\]()]*)[\])]")
_URL_TEXT = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)
# A capitalised name word or an initial ("J."); a full stop after a longer word ends the sentence.
_NAME_WORD = r"(?:[^\W\d_a-z\u00df-\u00ff](?:\.|[^\W\d_]*(?:[-'\u2019][^\W\d_]+)*))"
_BY_AUTHOR = re.compile(
    r"\bby\s+("
    + _NAME_WORD
    + r"(?:\s+"
    + _NAME_WORD
    + r"){0,3}(?:(?:\s*,\s*|\s+and\s+|\s*&\s*)"
    + _NAME_WORD
    + r"(?:\s+"
    + _NAME_WORD
    + r"){0,3})*)"
)
_AUTHOR_SPLIT = re.compile(r"\s*,\s*|\s+and\s+|\s*&\s*")
_BLOCK_TAGS = frozenset({"p", "li", "ul", "ol", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th"})


# --- normalisation ---------------------------------------------------------------------------


def normalize_phrase(text: str) -> str:
    """Case-fold, collapse whitespace and fold typographic apostrophes."""
    return _WHITESPACE.sub(" ", text.translate(_APOSTROPHES)).strip().casefold()


def letters_key(text: str) -> str:
    """Letters and digits only, case-folded: the basis of the similarity score."""
    return "".join(character for character in text.translate(_APOSTROPHES).casefold() if character.isalnum())


def similarity(left: str, right: str) -> float:
    """Similarity of two phrases on letters and digits (0..1)."""
    left_key, right_key = letters_key(left), letters_key(right)
    if not left_key or not right_key:
        return 0.0
    return SequenceMatcher(None, left_key, right_key, autojunk=False).ratio()


def _strip_possessive(word: str) -> str:
    return _POSSESSIVE.sub("", word)


def _word_count(text: str) -> int:
    return len([part for part in re.split(r"[\s\-]+", text) if letters_key(part)])


# --- common words ----------------------------------------------------------------------------


def common_word_language(language: str) -> str | None:
    """Map a language code ("en-US", "de_DE", "EN") to a built-in list, or None."""
    base = re.split(r"[-_]", language.strip(), maxsplit=1)[0].casefold()
    return base if base in COMMON_WORD_LANGUAGES else None


@functools.cache
def _common_words(language: str) -> frozenset[str]:
    resource = files("cast.transcripts").joinpath("common_words", f"{language}.txt")
    words = set()
    for line in resource.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if word and not word.startswith("#"):
            words.add(normalize_phrase(word))
    return frozenset(words)


def has_common_words(language: str) -> bool:
    """Whether a common-word list exists for this transcript language."""
    return common_word_language(language) is not None


def is_common_word(word: str, language: str) -> bool:
    """Whether ``word`` (one word, possessive ignored) is in the language's common-word list.

    Languages without a list have no common words.
    """
    base = common_word_language(language)
    if base is None:
        return False
    normalized = normalize_phrase(word)
    if not normalized or " " in normalized:
        return False
    words = _common_words(base)
    return normalized in words or _strip_possessive(normalized) in words


# --- parsing glossary text fields ------------------------------------------------------------


def _clean_line(line: str) -> str:
    return _WHITESPACE.sub(" ", line).strip()


def parse_contributor_variants(display_name: str, text: str) -> list[tuple[str, str]]:
    """Parse ``variant => replacement`` lines; a line without ``=>`` maps to ``display_name``.

    Blank lines, lines with an empty side and no-op lines are skipped. The same variant
    with different replacements is kept once per replacement, so the conflict is visible.
    """
    display_name = _clean_line(display_name)
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in text.splitlines():
        line = _clean_line(raw_line)
        if not line:
            continue
        if "=>" in line:
            variant, replacement = (_clean_line(part) for part in line.split("=>", 1))
        else:
            variant, replacement = line, display_name
        if not variant or not replacement or variant == replacement or not letters_key(variant):
            continue
        key = (normalize_phrase(variant), replacement)
        if key in seen:
            continue
        seen.add(key)
        pairs.append((variant, replacement))
    return pairs


def parse_term_variants(text: str) -> list[str]:
    """One variant per line; blanks and duplicates (after normalisation) are skipped."""
    variants: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        variant = _clean_line(raw_line)
        key = normalize_phrase(variant)
        if not letters_key(variant) or key in seen:
            continue
        seen.add(key)
        variants.append(variant)
    return variants


# --- episode terms from show notes -----------------------------------------------------------


class _ShowNotesParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.link_texts: list[str] = []
        self.blocks: list[str] = []
        self._link_depth = 0
        self._link_parts: list[str] = []
        self._block_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._link_depth += 1
            if self._link_depth == 1:
                self._link_parts = []
        elif tag in _BLOCK_TAGS:
            self._flush_block()

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link_depth:
            self._link_depth -= 1
            if not self._link_depth:
                self.link_texts.append(_clean_line("".join(self._link_parts)))
        elif tag in _BLOCK_TAGS:
            self._flush_block()

    def handle_data(self, data: str) -> None:
        if self._link_depth:
            self._link_parts.append(data)
        self._block_parts.append(data)

    def _flush_block(self) -> None:
        block = _clean_line("".join(self._block_parts))
        if block:
            self.blocks.append(block)
        self._block_parts = []

    def close(self) -> None:
        super().close()
        self._flush_block()


def _split_camel_case(word: str) -> str:
    return _CAMEL_BOUNDARY.sub(" ", word)


def _is_distinctive_token(token: str) -> bool:
    """CamelCase, acronyms and joined names stand on their own ("EuroPython", "DEPs", "spec-kit")."""
    letters = [character for character in token if character.isalpha()]
    if len(letters) < 2:
        return False
    if any(character.isupper() for character in token[1:]):
        return True
    return bool(re.search(r"[^\W_][-.][^\W_]", token))


def _without_trailing_numbers(text: str) -> str:
    """Drop an edition or year after a name ("DjangoCon Europe 2027"), not after "in" or "for"."""
    words = text.split(" ")
    while len(words) > 1 and _YEAR_OR_NUMBER.match(words[-1]) and words[-2][:1].isupper():
        words.pop()
    return " ".join(words)


def _terms_from_phrase(text: str) -> tuple[list[str], list[str], list[str]]:
    """Primary terms, derived terms and identifiers (repository, owner, host) of one link text or title."""
    primary: list[str] = []
    derived: list[str] = []
    identifiers: list[str] = []
    text = _clean_line(text).strip(" ,;")
    if not text:
        return primary, derived, identifiers
    if _URL_TEXT.match(text):
        host = re.sub(r"^(?:https?://)?(?:www\.)?", "", text, flags=re.IGNORECASE).split("/", 1)[0]
        if host:
            derived.append(host)
            identifiers.append(host)
        return primary, derived, identifiers
    for note in _BRACKET_NOTE.findall(text):
        derived.extend(part for part in re.split(r"\s*[,;]\s*", note) if part)
    text = _clean_line(_BRACKET_NOTE.sub("", text))
    for part in _TERM_SEPARATORS.split(text):
        part = part.strip(" ,;")
        if not part or part.startswith("@"):
            continue  # a handle is not how a name is spoken
        if re.fullmatch(r"[^\s/]+/[^\s/]+", part):
            owner, repo = part.split("/")
            derived.append(repo)
            identifiers.extend((owner, repo))
            if _split_camel_case(owner) != owner:
                derived.append(_split_camel_case(owner))
            continue
        # Speakers drop a leading article freely ("The Go-Giver"), so the term starts without it.
        part = re.sub(r"^(?:the|a|an)\s+(?=\S)", "", part, flags=re.IGNORECASE)
        primary.append(part)
        if " " not in part:
            identifiers.append(part)
        without_numbers = _without_trailing_numbers(part)
        if without_numbers != part:
            derived.append(without_numbers)
        tokens = _TOKEN.findall(part)
        if len(tokens) > 1:
            derived.extend(token for token in tokens if _is_distinctive_token(token))
    return primary, derived, identifiers


PRODUCT_PREFIXES = ("get", "use", "try")
MIN_PRODUCT_NAME_LETTERS = 4


def _product_names(identifier: str) -> list[str]:
    """Names behind a lowercase product prefix in an identifier ("getscaf" -> "scaf")."""
    names = []
    for label in re.split(r"[-./]", identifier):
        if not label.isalnum() or label != label.lower():
            continue
        for prefix in PRODUCT_PREFIXES:
            rest = label[len(prefix) :]
            if label.startswith(prefix) and sum(character.isalpha() for character in rest) >= MIN_PRODUCT_NAME_LETTERS:
                names.append(rest)
    return names


def _authors(block: str) -> list[str]:
    names: list[str] = []
    for match in _BY_AUTHOR.finditer(block):
        names.extend(name.strip() for name in _AUTHOR_SPLIT.split(match.group(1)) if name.strip())
    return names


def episode_terms(body_html: str, title: str = "") -> list[str]:
    """Canonical spellings from show-note link texts, "by <Author>" phrases and the title.

    Full link texts and author names come first, derived forms (parts, surnames,
    CamelCase tokens, repository names, URL hosts) after them; duplicates by letters are
    dropped. A lowercase repository, owner, host label or one-word link text starting with
    "get", "use" or "try" also yields the rest when it has at least four letters
    ("getscaf" -> "scaf"): projects are often named that way after their domain.
    """
    parser = _ShowNotesParser()
    parser.feed(body_html or "")
    parser.close()
    primary: list[str] = []
    derived: list[str] = []
    for phrase in [title, *parser.link_texts]:
        phrase_primary, phrase_derived, identifiers = _terms_from_phrase(phrase)
        primary.extend(phrase_primary)
        derived.extend(phrase_derived)
        derived.extend(name for identifier in identifiers for name in _product_names(identifier))
    for block in parser.blocks:
        for author in _authors(block):
            primary.append(author.rstrip("."))
            words = author.split()
            if len(words) > 1:
                derived.append(words[-1])
    terms: list[str] = []
    seen: set[str] = set()
    for term in [*primary, *derived]:
        term = _clean_line(term).strip(" ,;.:")
        key = letters_key(term)
        if len(key) < MIN_TARGET_LETTERS or key in seen:
            continue
        seen.add(key)
        terms.append(term)
    return terms


# --- effective glossary ----------------------------------------------------------------------


@dataclass(frozen=True)
class ContributorGlossary:
    """A credited contributor: canonical ``display_name`` and its ``transcript_variants`` text."""

    display_name: str
    transcript_variants: str = ""


@dataclass(frozen=True)
class ShowTerm:
    """A show glossary term: canonical ``term`` and its ``variants`` text (one per line)."""

    term: str
    variants: str = ""


@dataclass(frozen=True)
class ProposalTarget:
    text: str
    source: str


@dataclass(frozen=True)
class VariantEntry:
    """A listed phrase: replaced automatically when it has exactly one target."""

    variant: str
    targets: tuple[str, ...]
    source: str
    automatic: bool
    pattern: re.Pattern[str] = field(compare=False, repr=False)


def _word_pattern(word: str) -> str:
    parts = []
    for piece in _SHARP_S.split(word):
        if piece.casefold() == "ss":
            parts.append("(?:ss|ß|ẞ)")
        else:
            parts.append(re.escape(piece).replace("'", _APOSTROPHE_CLASS))
    return "".join(parts)


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Whole-phrase pattern matching what ``normalize_phrase`` treats as equal.

    Case-insensitive (simple case folding plus ß/ss), any whitespace between words, any
    supported apostrophe; offsets refer to the original text.
    """
    words = _clean_line(phrase.translate(_APOSTROPHES)).split(" ")
    body = r"\s+".join(_word_pattern(word) for word in words)
    return re.compile(_PHRASE_START + body + _PHRASE_END, re.IGNORECASE)


def phrase_spans(text: str, phrase: str) -> list[tuple[int, int]]:
    """Whole-phrase occurrences of ``phrase`` in ``text``, matched like listed variants."""
    if not letters_key(phrase):
        return []
    return [match.span() for match in _phrase_pattern(phrase).finditer(text)]


class EffectiveGlossary:
    """The glossary of one episode: contributor and show variants plus proposal targets.

    A normalised variant that maps to different replacements is a conflict: its
    matches become proposals for each target instead of automatic replacements.
    Show-term variants are automatic only when the transcript ``language`` has a
    common-word list and the variant is not a single common word; otherwise their
    matches are proposals. Pass ``""`` when the language is unknown.
    """

    def __init__(
        self,
        contributors: Iterable[ContributorGlossary] = (),
        show_terms: Iterable[ShowTerm] = (),
        episode_terms: Iterable[str] = (),
        *,
        language: str,
    ) -> None:
        self.language = language
        contributors = list(contributors)
        show_terms = list(show_terms)
        mapping: dict[str, dict[str, str]] = {}
        spelling: dict[str, str] = {}
        manual: set[str] = set()
        show_automatic = has_common_words(language)

        def add_variant(variant: str, replacement: str, source: str) -> None:
            key = normalize_phrase(variant)
            spelling.setdefault(key, variant)
            mapping.setdefault(key, {}).setdefault(replacement, source)
            if source == SOURCE_SHOW and (not show_automatic or is_common_word(variant, language)):
                manual.add(key)

        for contributor in contributors:
            for variant, replacement in parse_contributor_variants(
                contributor.display_name, contributor.transcript_variants
            ):
                add_variant(variant, replacement, SOURCE_CONTRIBUTOR)
        for show_term in show_terms:
            term = _clean_line(show_term.term)
            if not term:
                continue
            for variant in parse_term_variants(show_term.variants):
                if variant != term:
                    add_variant(variant, term, SOURCE_SHOW)

        self.replacement_map: dict[str, tuple[str, str]] = {}
        self.conflicts: dict[str, tuple[str, ...]] = {}
        entries: list[VariantEntry] = []
        for key, replacements in mapping.items():
            targets = tuple(replacements)
            if len(targets) > 1:
                self.conflicts[key] = targets
                source, automatic = SOURCE_CONFLICT, False
            else:
                source = replacements[targets[0]]
                automatic = key not in manual
                if automatic:
                    self.replacement_map[key] = (targets[0], source)
            entries.append(VariantEntry(spelling[key], targets, source, automatic, _phrase_pattern(spelling[key])))

        # Canonical spellings already present in the text are protected from shorter variants.
        protected: dict[str, str] = {}
        canonical = [
            *(contributor.display_name for contributor in contributors),
            *(term.term for term in show_terms),
            *(target for targets in mapping.values() for target in targets),
        ]
        for text in canonical:
            key = normalize_phrase(text)
            if letters_key(key) and key not in mapping:
                protected.setdefault(key, _clean_line(text))
        for text in protected.values():
            entries.append(VariantEntry(text, (), "", False, _phrase_pattern(text)))
        entries.sort(key=lambda entry: (-len(letters_key(entry.variant)), -len(entry.variant), entry.variant))
        self.entries: tuple[VariantEntry, ...] = tuple(entries)

        proposal_targets: list[ProposalTarget] = []
        seen: set[str] = set()

        def add_target(text: str, source: str) -> None:
            text = _clean_line(text)
            key = letters_key(text)
            if len(key) < MIN_TARGET_LETTERS or key in seen:
                return
            seen.add(key)
            proposal_targets.append(ProposalTarget(text, source))

        for contributor in contributors:
            add_target(contributor.display_name, SOURCE_CONTRIBUTOR)
        for contributor in contributors:
            for part in _clean_line(contributor.display_name).split(" "):
                add_target(part, SOURCE_CONTRIBUTOR)
            for _variant, replacement in parse_contributor_variants(
                contributor.display_name, contributor.transcript_variants
            ):
                add_target(replacement, SOURCE_CONTRIBUTOR)
        for show_term in show_terms:
            add_target(show_term.term, SOURCE_SHOW)
        for term in episode_terms:
            if _word_count(term) == 1 and is_common_word(term, language):
                continue
            add_target(term, SOURCE_EPISODE)
        self.proposal_targets: tuple[ProposalTarget, ...] = tuple(proposal_targets)


# --- matching --------------------------------------------------------------------------------


class Segment(Protocol):  # pragma: no cover - structural type, no runtime code
    @property
    def start_ms(self) -> int: ...

    @property
    def text(self) -> str: ...


class TextEdit(Protocol):  # pragma: no cover - structural type, no runtime code
    @property
    def start(self) -> int: ...

    @property
    def end(self) -> int: ...

    @property
    def original(self) -> str: ...

    @property
    def to(self) -> str: ...


@dataclass(frozen=True)
class TextSegment:
    start_ms: int
    text: str


@dataclass(frozen=True)
class Replacement:
    start_ms: int
    start: int
    end: int
    original: str
    to: str
    source: str


@dataclass(frozen=True)
class Proposal:
    start_ms: int
    start: int
    end: int
    original: str
    to: str
    source: str
    score: float


@dataclass
class ProposalGroup:
    """Proposals sharing one correct spelling; an editor decides them together."""

    to: str
    originals: list[tuple[str, int]]
    occurrences: list[Proposal]
    sources: tuple[str, ...]


def _overlaps(start: int, end: int, spans: Iterable[tuple[int, int]]) -> bool:
    return any(start < span_end and span_start < end for span_start, span_end in spans)


def _match_entries(text: str, glossary: EffectiveGlossary) -> list[tuple[int, int, VariantEntry]]:
    """Longest listed phrase first, no overlaps; protected canonical spellings block shorter ones."""
    matches: list[tuple[int, int, VariantEntry]] = []
    taken: list[tuple[int, int]] = []
    for entry in glossary.entries:
        for match in entry.pattern.finditer(text):
            start, end = match.span()
            if _overlaps(start, end, taken):
                continue
            taken.append((start, end))
            if entry.targets:
                matches.append((start, end, entry))
    matches.sort(key=lambda item: item[0])
    return matches


def find_replacements(segments: Sequence[Segment], glossary: EffectiveGlossary) -> list[Replacement]:
    """Automatic replacements of listed, non-conflicting variants."""
    replacements: list[Replacement] = []
    for segment in segments:
        for start, end, entry in _match_entries(segment.text, glossary):
            original = segment.text[start:end]
            if not entry.automatic or original == entry.targets[0]:
                continue
            replacements.append(Replacement(segment.start_ms, start, end, original, entry.targets[0], entry.source))
    return replacements


def _parts(text: str) -> list[str]:
    """Words of a term including CamelCase and joined parts ("DjangoCon" -> Django, Con)."""
    return [letters_key(part) for part in re.split(r"[\s\-./]+", _split_camel_case(text)) if letters_key(part)]


def _digits(key: str) -> str:
    return "".join(character for character in key if character.isdigit())


def _looks_like_domain(text: str) -> bool:
    return bool(re.search(r"[^\W_]\.[^\W\d_]{2,}$", text))


@dataclass(frozen=True)
class _Target:
    text: str
    source: str
    key: str
    word_count: int
    normalized: str
    part_keys: frozenset[str]
    pattern: re.Pattern[str] = field(compare=False, repr=False)

    @classmethod
    def build(cls, target: ProposalTarget) -> _Target:
        parts = _parts(target.text)
        part_keys = frozenset(
            "".join(parts[first:last])
            for first in range(len(parts))
            for last in range(first + 1, len(parts) + 1)
            if last - first < len(parts)
        )
        return cls(
            target.text,
            target.source,
            letters_key(target.text),
            _word_count(target.text),
            normalize_phrase(target.text),
            part_keys,
            _phrase_pattern(target.text),
        )

    @property
    def candidate_word_counts(self) -> range:
        if self.word_count == 1:
            # A single word may be split by the recogniser ("Button Down" for "Buttondown").
            return range(1, 3)
        return range(max(2, self.word_count - 1), self.word_count + 2)

    def is_spelled_by(self, candidate: _Candidate) -> bool:
        """The candidate already is this target (a lowercase identifier may be read aloud: "spec kit")."""
        return candidate.normalized == self.normalized or (
            candidate.key == self.key and self.text == self.text.lower()
        )

    def rejects(self, candidate: _Candidate) -> bool:
        """Candidates that are no misspelling of this target, whatever their similarity."""
        if candidate.words not in self.candidate_word_counts:
            return True
        if candidate.words > self.word_count and min(candidate.piece_lengths) < MIN_TARGET_LETTERS:
            return True  # a word split by the recogniser leaves no one- or two-letter piece
        if candidate.key in self.part_keys:
            return True  # a part of the term ("Django" for "DjangoCon") is no error
        candidate_digits, target_digits = _digits(candidate.key), _digits(self.key)
        if candidate_digits and target_digits and candidate_digits != target_digits:
            return True  # a different number names a different thing ("DEP 10", "DEP 19")
        return _looks_like_domain(candidate.text) != _looks_like_domain(self.text)


@dataclass(frozen=True)
class _Candidate:
    start: int
    end: int
    words: int
    key: str
    text: str
    normalized: str
    piece_lengths: tuple[int, ...]


def _candidates(text: str, max_words: int, language: str) -> list[_Candidate]:
    tokens = list(_TOKEN.finditer(text))
    candidates: list[_Candidate] = []
    for first in range(len(tokens)):
        for words in range(1, max_words + 1):
            last = first + words - 1
            if last >= len(tokens):
                break
            if words > 1 and text[tokens[last - 1].end() : tokens[last].start()].strip():
                break  # only whitespace may separate the words of a candidate
            start, end = tokens[first].start(), tokens[last].end()
            stripped = _strip_possessive(tokens[last].group(0))
            end -= len(tokens[last].group(0)) - len(stripped)
            phrase = text[start:end]
            if words == 1 and is_common_word(phrase, language):
                continue
            key = letters_key(phrase)
            if len(key) < MIN_TARGET_LETTERS:
                continue
            pieces = tuple(len(letters_key(token.group(0))) for token in tokens[first : last + 1])
            candidates.append(_Candidate(start, end, words, key, phrase, normalize_phrase(phrase), pieces))
    return candidates


def _score(candidate: _Candidate, target: _Target) -> tuple[float, int]:
    """Similarity and number of matching letters (0 when below the threshold)."""
    total = len(candidate.key) + len(target.key)
    if 2 * min(len(candidate.key), len(target.key)) < SIMILARITY_THRESHOLD * total:
        return 0.0, 0
    matcher = SequenceMatcher(None, candidate.key, target.key, autojunk=False)
    if matcher.real_quick_ratio() < SIMILARITY_THRESHOLD or matcher.quick_ratio() < SIMILARITY_THRESHOLD:
        return 0.0, 0
    matching = sum(block.size for block in matcher.get_matching_blocks())
    return 2 * matching / total, matching


def find_proposals(
    segments: Sequence[Segment],
    glossary: EffectiveGlossary,
    language: str,
    *,
    exclude: Sequence[Replacement] | None = None,
) -> list[Proposal]:
    """Proposals: listed variants that are not automatic, and fuzzy matches of glossary targets.

    Fuzzy matches compare word n-grams of one segment with each target on letters and
    digits (similarity >= 0.8). Never proposed: a single common word, a phrase that
    already spells the target (ignoring case) or overlaps such a spelling, a part of the target, a
    lowercase identifier read aloud, a different number, and spans covered by
    ``exclude`` (the automatic replacements; computed when omitted). On overlap the
    match with more matching letters wins, then the higher score, then the shorter span.
    """
    if exclude is None:
        exclude = find_replacements(segments, glossary)
    excluded: dict[int, list[tuple[int, int]]] = {}
    for replacement in exclude:
        excluded.setdefault(replacement.start_ms, []).append((replacement.start, replacement.end))
    targets = [_Target.build(target) for target in glossary.proposal_targets]
    max_words = max((target.candidate_word_counts.stop - 1 for target in targets), default=0)
    proposals: list[Proposal] = []
    for segment in segments:
        text = segment.text
        blocked = list(excluded.get(segment.start_ms, []))
        segment_proposals: list[Proposal] = []
        for start, end, entry in _match_entries(text, glossary):
            if entry.automatic or _overlaps(start, end, blocked):
                continue
            for target_text in entry.targets:
                segment_proposals.append(
                    Proposal(segment.start_ms, start, end, text[start:end], target_text, entry.source, 1.0)
                )
            blocked.append((start, end))
        candidates = [
            candidate
            for candidate in (_candidates(text, max_words, language) if targets else [])
            if not _overlaps(candidate.start, candidate.end, blocked)
        ]
        matches: list[tuple[tuple[int, float, int], _Candidate, _Target, float]] = []
        for target in targets:
            # Where the text already spells this target, overlapping phrases are no misspelling of it.
            present = [match.span() for match in target.pattern.finditer(text)]
            present.extend((c.start, c.end) for c in candidates if target.is_spelled_by(c))
            for candidate in candidates:
                if target.rejects(candidate) or _overlaps(candidate.start, candidate.end, present):
                    continue
                score, matching = _score(candidate, target)
                if score >= SIMILARITY_THRESHOLD:
                    rank = (-matching, -score, candidate.end - candidate.start)
                    matches.append((rank, candidate, target, score))
        matches.sort(key=lambda item: (item[0], item[1].start, item[2].text))
        taken: list[tuple[int, int]] = []
        for _rank, candidate, target, score in matches:
            if _overlaps(candidate.start, candidate.end, taken):
                continue
            taken.append((candidate.start, candidate.end))
            segment_proposals.append(
                Proposal(
                    segment.start_ms,
                    candidate.start,
                    candidate.end,
                    candidate.text,
                    target.text,
                    target.source,
                    round(score, 3),
                )
            )
        segment_proposals.sort(key=lambda proposal: (proposal.start, proposal.to))
        proposals.extend(segment_proposals)
    return proposals


def group_proposals(proposals: Iterable[Proposal]) -> list[ProposalGroup]:
    """Group proposals by correct spelling (case-sensitive), in order of first occurrence."""
    groups: dict[str, ProposalGroup] = {}
    counts: dict[str, dict[str, int]] = {}
    for proposal in proposals:
        group = groups.get(proposal.to)
        if group is None:
            group = groups[proposal.to] = ProposalGroup(proposal.to, [], [], ())
            counts[proposal.to] = {}
        group.occurrences.append(proposal)
        counts[proposal.to][proposal.original] = counts[proposal.to].get(proposal.original, 0) + 1
        if proposal.source not in group.sources:
            group.sources = (*group.sources, proposal.source)
    for to, group in groups.items():
        group.originals = list(counts[to].items())
    return list(groups.values())


def apply_replacements(text: str, replacements: Iterable[TextEdit]) -> str:
    """Apply non-overlapping edits to one segment's text.

    Raises ``ValueError`` when an edit is empty, out of bounds, overlaps another edit or no
    longer matches the text.
    """
    ordered = sorted(replacements, key=lambda edit: edit.start)
    pieces: list[str] = []
    position = 0
    for edit in ordered:
        if (
            edit.start < position
            or edit.end <= edit.start
            or edit.end > len(text)
            or text[edit.start : edit.end] != edit.original
        ):
            raise ValueError(f"replacement {edit.original!r} at {edit.start}:{edit.end} does not match the text")
        pieces.append(text[position : edit.start])
        pieces.append(edit.to)
        position = edit.end
    pieces.append(text[position:])
    return "".join(pieces)
