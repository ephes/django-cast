"""Synthetic browser URL boundary cases shared by view and Chromium checks."""

UNSAFE_COMPARE_PATHS = [
    "/\\outside.example/x",
    "/\\\\outside.example/x",
    "//outside.example/x",
    "///outside.example/x",
    "/\t/outside.example/x",
    "/\n/outside.example/x",
    "/\r/outside.example/x",
    " /local/",
    "/local/ ",
    "/local/\x00",
    "/local/\x1f",
    "/local/\x7f",
    "/local/\x85",
]
LOCAL_COMPARE_PATHS = [
    "/page/",
    "/page/?foo=bar&baz=qux",
    "/%5Coutside.example/x",
    "/page/?next=%2F%2Foutside.example",
]
