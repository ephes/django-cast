.. _search_overview:

******
Search
******

Django Cast supports full-text search and faceted filtering on blog and podcast
list pages. Filtering is handled by ``PostFilterset`` (in ``cast.filters``) and
is available in two contexts:

- Blog/podcast list pages (Wagtail page views)
- Wagtail API pages listing when ``use_post_filter=true``

Filter Parameters
=================

The filter parameter names are shared between UI routes and API routes.

- ``search``: full-text search via Django Cast's modelsearch wrapper
- ``date_after`` and ``date_before``: date range filter for ``visible_date`` (from the ``date`` filter)
- ``date_facets``: single month facet, format ``YYYY-MM``
- ``category_facets``: category slug
- ``tag_facets``: tag slug
- ``o``: ordering for ``visible_date`` (``visible_date`` or ``-visible_date``)

Default configuration:

.. code-block:: python

    CAST_FILTERSET_FACETS = [
        "search",
        "date",
        "date_facets",
        "category_facets",
        "tag_facets",
        "o",
    ]

Search and Filter Examples
==========================

Blog list routes (example slug ``styleguide-blog``):

.. code-block:: text

    /styleguide-blog/?search=python
    /styleguide-blog/?date_after=2026-01-01&date_before=2026-12-31
    /styleguide-blog/?date_facets=2026-02&tag_facets=django
    /styleguide-blog/?category_facets=til&o=-visible_date

Wagtail API pages endpoint (if cast is mounted at ``/cast/``):

.. code-block:: text

    /cast/api/wagtail/pages/?type=cast.Post&child_of=4&use_post_filter=true&search=python
    /cast/api/wagtail/pages/?type=cast.Post&child_of=4&use_post_filter=true&date_facets=2026-02

Facet Behavior
==============

- Search input is normalized before it reaches modelsearch. Null bytes are
  stripped, repeated whitespace/hyphen runs are collapsed, leading/trailing
  whitespace is removed, and very long values are capped. Malformed or
  punctuation-only public searches return no results instead of raising a
  server error.
- In the default (legacy) mode, facet counts reflect the currently filtered
  queryset. The ``?mode=modal`` API uses a different counting strategy; see
  :ref:`conjunctive_vs_disjunctive` for details.
- Tag/category facet options with count ``0`` are omitted from the standard filterset choices.
- Date facets are month buckets generated from ``visible_date``.
- Invalid facet values are ignored:
  - ``date_facets`` must parse as ``YYYY-MM``.
  - ``tag_facets`` and ``category_facets`` must pass Django slug validation.
- Generated facet links intentionally drop ``page`` from the query string to avoid broken pagination URLs.

.. _conjunctive_vs_disjunctive:

Conjunctive vs Disjunctive Faceting
===================================

django-cast provides two facet API modes. The default (legacy) mode returns
counts matching all currently active filters. The modal mode (``?mode=modal``)
adjusts counts per facet group so a UI can show "what happens if I switch this
facet value next?".

Both modes are documented in :ref:`Modal Facet API <modal_facet_api>`.

These correspond to two counting strategies common in faceted navigation.

Conjunctive faceting
--------------------

Counts are computed from the fully filtered result set (all active filters applied).

This is the strategy used by the default (legacy) facet API.

Disjunctive faceting
--------------------

For a given facet group, counts are computed with that group temporarily excluded,
while keeping the other active filters.

This is the strategy used by the modal facet API (``?mode=modal``).

Practical example
-----------------

Assume posts:

- Post A: ``category=til``, ``tag=python``
- Post B: ``category=til``, ``tag=django``
- Post C: ``category=weeknotes``, ``tag=python``

Active URL state:

.. code-block:: text

    /styleguide-blog/?category_facets=til&tag_facets=python

Conjunctive tag counts (legacy):

- Current result set is only Post A.
- Tag options from that set are effectively ``python (1)``.
- ``django`` is not available until you first clear the tag filter.

Disjunctive tag counts (modal):

- Keep ``category_facets=til`` but exclude the current tag filter while counting tag options.
- Eligible posts are Post A and Post B.
- Tag options become ``python (1)`` and ``django (1)``.
- Clicking ``django`` switches directly to:

.. code-block:: text

    /styleguide-blog/?category_facets=til&tag_facets=django

Why django-cast has both
------------------------

- Legacy mode keeps backward-compatible behavior for existing clients.
- ``mode=modal`` supports one-click switching inside a facet group (without a clear-first step).
- The total result count still reflects all active filters combined.
- Each facet group's option counts answer: "if I change only this group, how many results would I get?".
- See :doc:`../reference/api` for exact response fields (``result_count``, ``all_count``, ``options``).

.. _modal_facet_api:

Modal Facet API
===============

For modal UIs, use ``/cast/api/facet_counts/<blog_id>/?mode=modal`` (path prefix depends on how you include ``cast.urls``).

Modal payloads are calculated by ``cast.modal_facet_counts.get_modal_facet_counts`` and return:

- ``result_count`` for the fully selected state
- Per-group ``all_count`` with that group temporarily excluded
- ``options`` including zero-count values so the modal can keep the full facet universe visible

See :doc:`../reference/api` for exact response shapes.

Architecture Notes
==================

For the end-to-end request/data flow (blog queryset, ``PostFilterset``, legacy serializer path, and modal API path), see :ref:`search_facet_architecture`.
