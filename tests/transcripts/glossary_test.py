import pytest

from cast.transcripts import glossary
from cast.transcripts.glossary import (
    COMMON_WORD_LANGUAGES,
    ContributorGlossary,
    EffectiveGlossary,
    Proposal,
    Replacement,
    ShowTerm,
    TextSegment,
    apply_replacements,
    common_word_language,
    episode_terms,
    find_proposals,
    find_replacements,
    group_proposals,
    has_common_words,
    is_common_word,
    letters_key,
    normalize_phrase,
    parse_contributor_variants,
    parse_term_variants,
    similarity,
)


def segments(*texts: str) -> list[TextSegment]:
    return [TextSegment(index * 1000, text) for index, text in enumerate(texts)]


@pytest.fixture
def jon_glossary() -> EffectiveGlossary:
    return EffectiveGlossary(
        [ContributorGlossary("Jon Doe", "John Doe => Jon Doe\nJohn => Jon")],
        language="en",
    )


# --- normalisation and common words ---


def test_normalize_phrase_folds_case_whitespace_and_apostrophes():
    assert normalize_phrase("  John’s   BIG\tidea ") == "john's big idea"


def test_letters_key_and_similarity():
    assert letters_key("Go-Giver, 2nd!") == "gogiver2nd"
    assert similarity("Button Down", "Buttondown") == 1.0
    assert similarity("...", "Buttondown") == 0.0
    assert 0.8 < similarity("Foxy Talent", "Foxley Talent") < 1.0


@pytest.mark.parametrize(
    ("language", "expected"),
    [("en", "en"), ("en-US", "en"), ("DE_de", "de"), (" de ", "de"), ("fr", None), ("", None)],
)
def test_common_word_language(language, expected):
    assert common_word_language(language) == expected


def test_common_word_lists_exist_for_supported_languages():
    assert COMMON_WORD_LANGUAGES == ("de", "en")
    assert has_common_words("en-GB")
    assert not has_common_words("fr")


def test_is_common_word():
    assert is_common_word("rough", "en")
    assert is_common_word("Kind", "en-US")
    assert is_common_word("people’s", "en")  # possessive ignored
    assert is_common_word("nicht", "de")
    assert not is_common_word("Gunicorn", "en")
    assert not is_common_word("rough", "fr")  # no list, no common words
    assert not is_common_word("the end", "en")  # one word only
    assert not is_common_word("  ", "en")


def test_common_word_files_have_source_header():
    path = glossary.files("cast.transcripts").joinpath("common_words", "en.txt")
    header = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("#")]
    assert any("Tatoeba" in line for line in header)
    assert any("CC BY 2.0 FR" in line for line in header)
    assert "#" not in "".join(glossary._common_words("en"))


# --- parsing glossary fields ---


def test_parse_contributor_variants():
    text = "\n".join(
        [
            "John Doe => Jon Doe",
            "  John   =>  Jon ",
            "Jonny",
            "",
            "=> Jon",
            "Jhon =>",
            "Jon Doe => Jon Doe",
            "...",
            "john => Jon",  # duplicate after normalisation
        ]
    )
    assert parse_contributor_variants(" Jon  Doe ", text) == [
        ("John Doe", "Jon Doe"),
        ("John", "Jon"),
        ("Jonny", "Jon Doe"),
    ]


def test_parse_term_variants():
    assert parse_term_variants("Gunacorn\n\n gunacorn \nGunna  Corn\n--\n") == ["Gunacorn", "Gunna Corn"]


# --- episode terms ---


SHOW_NOTES = """
<p>Links</p>
<ul>
  <li><a href="https://example.com/">Widget Works</a></li>
  <li><a href="https://example.com/a">Widget Works YouTube</a></li>
  <li><a href="https://example.com/b">The Quiet Engine</a> by Ada Quill</li>
  <li><a href="https://example.com/c">The Mind Map</a> by Gale Ryland [Host]</li>
  <li><a href="https://example.com/d">The Kind Giver</a> by Bo Barg and Jo Mahn</li>
  <li><a href="https://github.com/MaraLeeBond/zapper">MaraLeeBond/zapper</a> - run things</li>
  <li><a href="https://github.com/plainowner/slowpoke">plainowner/slowpoke</a></li>
  <li><a href="https://example.com/e">PyGala Summit 2031 (Lisbon, Portugal)</a></li>
  <li><a href="https://example.com/f">Counting Pi: When Sums Go Wrong</a></li>
  <li><a href="https://example.com/g">Channel: @someshow</a></li>
  <li><a href="https://example.com/h">Open RFCs from the wiki-tool repo</a></li>
  <li><a href="https://example.com/i">Hiring in 2031</a></li>
  <li><a href="https://example.com/j"> </a><a href="https://example.com/k">https://</a></li>
  <li><a href="https://example.com/l">X</a></li>
</ul>
<p>Brought to you by <a href="https://zipmail.example/">Zipmail</a>.
See <a href="https://www.zipmail.example/offer">https://www.zipmail.example/offer</a>.</p>
<p>A recap by Will</p>
<p>Typography by Elliot J. Stock.</p>
"""


def test_episode_terms_from_show_notes():
    terms = episode_terms(SHOW_NOTES, "Some Show 12 - Mara Lee Bond")
    for expected in [
        "Some Show 12",
        "Mara Lee Bond",
        "Widget Works",
        "Quiet Engine",
        "Mind Map",
        "Kind Giver",
        "Ada Quill",
        "Gale Ryland",
        "Bo Barg",
        "Jo Mahn",
        "zapper",
        "slowpoke",
        "PyGala Summit 2031",
        "PyGala Summit",
        "PyGala",
        "Lisbon",
        "Portugal",
        "Counting Pi",
        "When Sums Go Wrong",
        "RFCs",
        "wiki-tool",
        "Zipmail",
        "zipmail.example",
        "Will",
        "Quill",
        "Ryland",
        "Elliot J. Stock",
        "Mahn",
        "Hiring in 2031",
        "Some Show",
    ]:
        assert expected in terms
    for unexpected in [
        "Mara Lee Bond/zapper",
        "plainowner",
        "Host",
        "someshow",
        "Hiring in",
        "The Quiet Engine",
        "X",
        "Zipmail. See",
    ]:
        assert unexpected not in terms
    assert terms.index("Gale Ryland") < terms.index("Ryland")  # full names before derived parts
    assert len({letters_key(term) for term in terms}) == len(terms)


def test_episode_terms_handles_nested_links_and_empty_input():
    assert episode_terms("") == []
    assert episode_terms('<p><a href="#">Outer <a href="#">Inner</a> <span>Link</span></a></p></a>') == [
        "Outer Inner Link"
    ]


# --- effective glossary ---


def test_effective_glossary_replacement_map_and_targets():
    effective = EffectiveGlossary(
        [
            ContributorGlossary("Jon Doe", "John Doe => Jon Doe\nJohn => Jon"),
            ContributorGlossary("Al Bo", ""),
        ],
        [ShowTerm("Gunicorn", "Gunacorn\nGunicorn"), ShowTerm("  ", "ignored")],
        ["Widget Works", "Gunicorn", "kind", "Zapper"],
        language="en",
    )
    assert effective.replacement_map == {
        "john doe": ("Jon Doe", "contributor"),
        "john": ("Jon", "contributor"),
        "gunacorn": ("Gunicorn", "show"),
    }
    assert effective.conflicts == {}
    targets = [(target.text, target.source) for target in effective.proposal_targets]
    assert targets == [
        ("Jon Doe", "contributor"),
        ("Al Bo", "contributor"),
        ("Jon", "contributor"),
        ("Doe", "contributor"),
        ("Gunicorn", "show"),
        ("Widget Works", "episode"),
        ("Zapper", "episode"),
    ]


def test_conflicting_variants_are_not_automatic():
    effective = EffectiveGlossary(
        [ContributorGlossary("Jon Doe", "John => Jon"), ContributorGlossary("Johan Roe", "John => Johan")],
        language="en",
    )
    assert effective.replacement_map == {}
    assert effective.conflicts == {"john": ("Jon", "Johan")}
    found = segments("Thanks, John.")
    assert find_replacements(found, effective) == []
    proposals = find_proposals(found, effective, "en")
    assert [(p.original, p.to, p.source, p.score) for p in proposals] == [
        ("John", "Johan", "conflict", 1.0),
        ("John", "Jon", "conflict", 1.0),
    ]


def test_same_replacement_from_contributor_and_show_is_no_conflict():
    effective = EffectiveGlossary(
        [ContributorGlossary("Jon Doe", "John => Jon")], [ShowTerm("Jon", "John")], language="en"
    )
    assert effective.replacement_map == {"john": ("Jon", "contributor")}


def test_show_variants_need_a_common_word_list():
    show_terms = [ShowTerm("Gunicorn", "Gunacorn")]
    unsupported = EffectiveGlossary(show_terms=show_terms, language="fr")
    assert unsupported.replacement_map == {}
    found = segments("On utilise Gunacorn.")
    assert find_replacements(found, unsupported) == []
    proposals = find_proposals(found, unsupported, "fr")
    assert [(p.original, p.to, p.source, p.score) for p in proposals] == [("Gunacorn", "Gunicorn", "show", 1.0)]
    assert EffectiveGlossary(show_terms=show_terms, language="en").replacement_map == {
        "gunacorn": ("Gunicorn", "show")
    }
    # an unknown language never allows automatic show-term replacement
    assert EffectiveGlossary(show_terms=[ShowTerm("Ruff", "rough")], language="").replacement_map == {}


def test_common_word_show_variant_is_only_a_proposal():
    effective = EffectiveGlossary(show_terms=[ShowTerm("Ruff", "rough")], language="en")
    assert effective.replacement_map == {}
    found = segments("We lint with rough.")
    assert find_replacements(found, effective) == []
    assert [(p.original, p.to) for p in find_proposals(found, effective, "en")] == [("rough", "Ruff")]


# --- automatic replacement ---


def test_find_replacements_whole_words_longest_first_and_possessives(jon_glossary):
    found = segments(
        "Welcome John Doe, and John's book.",
        "Johnson and Johnny are not John’s.",
        "JOHN said hi to john-paul and pre-John and john.doe and John'll.",
        "Jon Doe and Jon are already right.",
    )
    replacements = find_replacements(found, jon_glossary)
    assert [(r.start_ms, r.original, r.to, r.source) for r in replacements] == [
        (0, "John Doe", "Jon Doe", "contributor"),
        (0, "John", "Jon", "contributor"),
        (1000, "John", "Jon", "contributor"),
        (2000, "JOHN", "Jon", "contributor"),
        (2000, "John", "Jon", "contributor"),
    ]
    by_segment: dict[int, list[Replacement]] = {}
    for replacement in replacements:
        by_segment.setdefault(replacement.start_ms, []).append(replacement)
    assert apply_replacements(found[0].text, by_segment[0]) == "Welcome Jon Doe, and Jon's book."
    assert apply_replacements(found[1].text, by_segment[1000]) == "Johnson and Johnny are not Jon’s."
    assert apply_replacements(found[2].text, by_segment[2000]) == (
        "Jon said hi to john-paul and pre-John and john.doe and Jon'll."
    )


def test_find_replacements_skips_identical_text():
    effective = EffectiveGlossary([ContributorGlossary("Jon Doe", "jon => Jon")], language="en")
    assert find_replacements(segments("Jon and jon."), effective) == [
        Replacement(0, 8, 11, "jon", "Jon", "contributor")
    ]


def test_canonical_spelling_protects_against_shorter_variants():
    effective = EffectiveGlossary(
        show_terms=[ShowTerm("Django on the Medd", ""), ShowTerm("Medd", "Mett")], language="en"
    )
    assert find_replacements(segments("Django on the Mett", "Django on the Medd and the Mett"), effective) == [
        Replacement(0, 14, 18, "Mett", "Medd", "show"),
        Replacement(1000, 27, 31, "Mett", "Medd", "show"),
    ]


# --- proposals ---


def test_find_proposals_fuzzy_matches(jon_glossary):
    effective = EffectiveGlossary(
        [ContributorGlossary("Jon Doe", "John => Jon")],
        episode_terms=["Buttondown", "Farhan Ali Raza", "Go-Giver", "Gilbert Ryle", "Foxley Talent"],
        language="en",
    )
    found = segments(
        "Brought to you by Button Down and Buttonown is great.",
        "An app by Fahan Aliraza, the go givers, and Gilbert Riley's book.",
        "I work at Foxy Talent, John.",
    )
    replacements = find_replacements(found, effective)
    proposals = find_proposals(found, effective, "en", exclude=replacements)
    assert [(p.start_ms, p.original, p.to, p.source) for p in proposals] == [
        (0, "Button Down", "Buttondown", "episode"),
        (0, "Buttonown", "Buttondown", "episode"),
        (1000, "Fahan Aliraza", "Farhan Ali Raza", "episode"),
        (1000, "go givers", "Go-Giver", "episode"),
        (1000, "Gilbert Riley", "Gilbert Ryle", "episode"),
        (2000, "Foxy Talent", "Foxley Talent", "episode"),
    ]
    first = proposals[0]
    assert found[0].text[first.start : first.end] == "Button Down"
    assert first.score == 1.0
    assert 0.8 <= proposals[1].score < 1.0
    # the automatic replacement of "John" is never proposed again
    assert find_proposals(found, effective, "en") == proposals


def test_find_proposals_skips_common_words_and_existing_spellings():
    effective = EffectiveGlossary(
        [ContributorGlossary("Will Roe")],
        episode_terms=["spec-kit", "DjangoCon", "DEP 19", "sixfeetup.com", "Six Feet Up", "Kinde"],
        language="en",
    )
    found = segments(
        "I will be there, Will.",
        "Use the spec kit with Django at DjangoCon or Django.",
        "DEP 10 and Deb 19 matter.",
        "Visit sixfeetup.com or the Six Feed Up site.",
        "That kind of thing, at the end.",
    )
    proposals = find_proposals(found, effective, "en")
    assert [(p.original, p.to) for p in proposals] == [
        ("Deb 19", "DEP 19"),
        ("Six Feed Up", "Six Feet Up"),
    ]


def test_find_proposals_never_spans_segments_and_respects_separators():
    effective = EffectiveGlossary(episode_terms=["Foxley Talent"], language="en")
    assert find_proposals(segments("We met Foxy", "Talent today."), effective, "en") == []
    assert find_proposals(segments("Foxy, Talent"), effective, "en") == []


def test_find_proposals_prefers_more_matching_letters():
    effective = EffectiveGlossary(episode_terms=["Django on the Med", "DjangoCon"], language="en")
    proposals = find_proposals(segments("A talk about Django on the Met today."), effective, "en")
    assert [(p.original, p.to) for p in proposals] == [("Django on the Met", "Django on the Med")]


def test_find_proposals_without_targets():
    assert find_proposals(segments("Nothing to see."), EffectiveGlossary(language="en"), "en") == []


def test_find_proposals_unsupported_language_allows_single_words():
    effective = EffectiveGlossary(episode_terms=["Gunicorn"], language="xx")
    assert [(p.original, p.to) for p in find_proposals(segments("Gunacorn"), effective, "xx")] == [
        ("Gunacorn", "Gunicorn")
    ]


def test_target_rules():
    target = glossary._Target.build(glossary.ProposalTarget("Six Feet Up", "episode"))
    assert list(target.candidate_word_counts) == [2, 3, 4]
    single = glossary._Target.build(glossary.ProposalTarget("Buttondown", "episode"))
    assert list(single.candidate_word_counts) == [1, 2]

    def candidate(text: str) -> glossary._Candidate:
        found = glossary._candidates(text, 4, "xx")
        return max(found, key=lambda item: item.end - item.start)

    assert single.rejects(candidate("Button Down Bay"))  # too many words
    assert single.rejects(candidate("Buttondow n"))  # a one-letter piece
    assert not single.rejects(candidate("Button Down"))
    assert target.rejects(candidate("Six Feet"))  # part of the term
    assert glossary._Target.build(glossary.ProposalTarget("DEP 19", "episode")).rejects(candidate("DEP 10"))
    assert single.rejects(candidate("buttondown.com"))
    assert glossary._Target.build(glossary.ProposalTarget("spec-kit", "episode")).is_spelled_by(candidate("spec kit"))
    assert not glossary._Target.build(glossary.ProposalTarget("Go-Giver", "episode")).is_spelled_by(
        candidate("go giver")
    )


def test_score_filters():
    target = glossary._Target.build(glossary.ProposalTarget("abcdef", "episode"))
    candidates = {c.text: c for c in glossary._candidates("abcdeg uvwxyz abc", 1, "xx")}
    assert glossary._score(candidates["abcdeg"], target)[0] == pytest.approx(5 / 6)
    assert glossary._score(candidates["uvwxyz"], target) == (0.0, 0)
    assert glossary._score(candidates["abc"], target) == (0.0, 0)


def test_candidates_skip_short_keys():
    assert [c.text for c in glossary._candidates("ab xy", 2, "xx")] == ["ab xy"]


# --- grouping and applying ---


def test_group_proposals_by_correct_spelling():
    proposals = [
        Proposal(0, 0, 8, "Gunacorn", "Gunicorn", "show", 0.9),
        Proposal(1000, 0, 10, "Gunna Corn", "Gunicorn", "episode", 0.85),
        Proposal(2000, 4, 12, "Gunacorn", "Gunicorn", "show", 0.9),
        Proposal(3000, 0, 5, "Scaff", "scaf", "episode", 0.89),
    ]
    groups = group_proposals(proposals)
    assert [group.to for group in groups] == ["Gunicorn", "scaf"]
    assert groups[0].originals == [("Gunacorn", 2), ("Gunna Corn", 1)]
    assert groups[0].sources == ("show", "episode")
    assert groups[0].occurrences == proposals[:3]
    assert groups[1].originals == [("Scaff", 1)]


def test_apply_replacements():
    text = "Hey John, meet Gunacorn."
    edits = [
        Replacement(0, 15, 23, "Gunacorn", "Gunicorn", "show"),
        Proposal(0, 4, 8, "John", "Jon", "contributor", 1.0),
    ]
    assert apply_replacements(text, edits) == "Hey Jon, meet Gunicorn."
    assert apply_replacements(text, []) == text
    with pytest.raises(ValueError):
        apply_replacements(text, [Replacement(0, 4, 8, "Jane", "Jon", "contributor")])
    with pytest.raises(ValueError):
        apply_replacements(text, [Replacement(0, 4, 8, "John", "Jon", "x"), Replacement(0, 6, 8, "hn", "x", "x")])


def test_spelled_target_only_blocks_its_own_proposals():
    effective = EffectiveGlossary(
        show_terms=[ShowTerm("Django", "")], episode_terms=["django-mail-auth"], language="en"
    )
    proposals = find_proposals(segments("A shout out to Django Mailoth today."), effective, "en")
    assert [(p.original, p.to) for p in proposals] == [("Django Mailoth", "django-mail-auth")]


def test_episode_terms_product_prefixes():
    notes = """
    <ul>
      <li><a href="#">getwidgo</a>, <a href="#">tryit</a>, <a href="#">Usefulthing</a></li>
      <li><a href="#">acme/usequark</a> and <a href="https://trybloop.example/">https://trybloop.example/</a></li>
      <li><a href="#">get_zapp</a> <a href="#">Lots of words</a></li>
    </ul>
    """
    terms = episode_terms(notes)
    assert {"getwidgo", "widgo", "quark", "bloop"} <= set(terms)
    assert not {"it", "fulthing", "zapp"} & set(terms)


def test_product_prefix_remainder_is_a_proposal_target():
    effective = EffectiveGlossary(
        episode_terms=episode_terms('<p><a href="https://example.com/getwidgo">getwidgo</a></p>'), language="en"
    )
    proposals = find_proposals(segments("We built Widgoo with widgo."), effective, "en")
    assert [(p.original, p.to, p.source) for p in proposals] == [("Widgoo", "widgo", "episode")]


# --- review regressions ---


def test_parse_contributor_variants_keeps_each_distinct_replacement():
    assert parse_contributor_variants("Jon Doe", "John => Jon\njohn => Johan\nJOHN => Jon") == [
        ("John", "Jon"),
        ("john", "Johan"),
    ]


def test_same_variant_with_two_targets_in_one_contributor_is_a_conflict():
    effective = EffectiveGlossary([ContributorGlossary("Jon Doe", "John => Jon\njohn => Johan")], language="en")
    assert effective.replacement_map == {}
    assert effective.conflicts == {"john": ("Jon", "Johan")}
    found = segments("Hi John.")
    assert find_replacements(found, effective) == []
    assert [p.to for p in find_proposals(found, effective, "en")] == ["Johan", "Jon"]


def test_contributor_and_show_term_with_different_targets_conflict():
    effective = EffectiveGlossary(
        [ContributorGlossary("Jon Doe", "John => Jon")], [ShowTerm("Johan", "john")], language="en"
    )
    assert effective.conflicts == {"john": ("Jon", "Johan")}


def test_german_common_words_include_function_words():
    for word in ["das", "er", "mit", "als", "um", "weiß", "Weiss", "und", "nicht"]:
        assert is_common_word(word, "de"), word
    assert not is_common_word("Tom", "de")
    effective = EffectiveGlossary(show_terms=[ShowTerm("Dask", "das")], language="de")
    assert effective.replacement_map == {}
    assert find_replacements(segments("Das ist gut."), effective) == []


@pytest.mark.parametrize(
    "text", ["O\u2018Brian", "O\u2019Brian", "O'Brian", "O\u02bcBrian", "Brian_Smith", "my_Brian"]
)
def test_variant_never_matches_inside_identifier_or_apostrophe_joined_token(text):
    effective = EffectiveGlossary([ContributorGlossary("Bryan Roe", "Brian => Bryan")], language="en")
    assert find_replacements(segments(text), effective) == []


@pytest.mark.parametrize("apostrophe", ["'", "\u2019", "\u2018", "\u02bc"])
@pytest.mark.parametrize(
    "text", ["Al{a}Qaeda", "Al{a}ana", "Al{a}s_x", "x{a}Al", "Al{a}s.com", "Al{a}s-Qaeda", "Al{a}s'ana", "Al{a}ll/x"]
)
def test_variant_never_matches_before_or_after_an_apostrophe_joined_word(apostrophe, text):
    effective = EffectiveGlossary([ContributorGlossary("Alan Roe", "Al => Alan")], language="en")
    assert find_replacements(segments(text.format(a=apostrophe)), effective) == []


@pytest.mark.parametrize("suffix", ["s", "S", "d", "ll", "re", "ve", "m", "t"])
def test_contraction_suffix_is_kept(suffix):
    effective = EffectiveGlossary([ContributorGlossary("Alan Roe", "Al => Alan")], language="en")
    found = segments(f"Al'{suffix} here, Al' there")
    assert apply_replacements(found[0].text, find_replacements(found, effective)) == f"Alan'{suffix} here, Alan' there"


@pytest.mark.parametrize("apostrophe", ["'", "\u2019", "\u2018", "\u02bc"])
def test_possessive_with_any_supported_apostrophe(apostrophe):
    effective = EffectiveGlossary([ContributorGlossary("Bryan Roe", "Brian => Bryan")], language="en")
    found = segments(f"Brian{apostrophe}s idea")
    replacements = find_replacements(found, effective)
    assert apply_replacements(found[0].text, replacements) == f"Bryan{apostrophe}s idea"


@pytest.mark.parametrize("text", ["Großkatzo", "grosskatzo", "GROSSKATZO", "GROẞKATZO"])
def test_sharp_s_variants_match_like_normalize_phrase(text):
    effective = EffectiveGlossary(show_terms=[ShowTerm("Grosskatz", "Großkatzo")], language="de")
    assert normalize_phrase(text) == normalize_phrase("Großkatzo")
    assert [(r.original, r.to) for r in find_replacements(segments(f"Die {text} kommt"), effective)] == [
        (text, "Grosskatz")
    ]


@pytest.mark.parametrize(
    "edit",
    [
        Replacement(0, 0, 100, "abc", "x", "show"),
        Replacement(0, 100, 100, "", "x", "show"),
        Replacement(0, 2, 2, "", "x", "show"),
        Replacement(0, 2, 1, "", "x", "show"),
        Replacement(0, -1, 1, "a", "x", "show"),
    ],
)
def test_apply_replacements_rejects_bad_spans(edit):
    with pytest.raises(ValueError):
        apply_replacements("abc", [edit])
