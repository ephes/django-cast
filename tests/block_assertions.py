"""Content comparisons for tests whose contract excludes top-level block identity.

Identity retention, UUID allocation and rejection have dedicated round-trip tests.
Nested values (including media IDs and gallery-item identities) remain exact.
"""


def block_values(blocks: list[dict]) -> list[dict]:
    return [{key: value for key, value in block.items() if key not in {"id", "existing_block_id"}} for block in blocks]
