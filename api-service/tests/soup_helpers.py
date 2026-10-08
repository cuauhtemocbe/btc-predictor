"""Typed accessors for BeautifulSoup lookups in the API tests."""

from typing import Any

from bs4 import BeautifulSoup, Tag


def find_tag(root: BeautifulSoup | Tag, *args: Any, **kwargs: Any) -> Tag:
    """Return the first tag matching ``root.find(...)``, failing the test if absent."""
    found = root.find(*args, **kwargs)
    assert isinstance(found, Tag), f"no tag matches {args} {kwargs}"
    return found


def attribute(tag: Tag, name: str) -> str:
    """Return a single-valued attribute of ``tag`` as a string."""
    value = tag.get(name)
    assert isinstance(value, str), f"attribute {name!r} is not a string: {value!r}"
    return value
