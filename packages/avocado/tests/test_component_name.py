"""Tests for codegen._to_component_name — Figma node name → PascalCase."""

from __future__ import annotations

from avocado.generator.codegen import _to_component_name


def test_simple_name() -> None:
    assert _to_component_name("Confirm") == "Confirm"


def test_spaces_pascal_case() -> None:
    assert _to_component_name("Confirm Customer Details") == "ConfirmCustomerDetails"


def test_hyphens_and_underscores() -> None:
    assert _to_component_name("booking-details_card") == "BookingDetailsCard"


def test_colon_and_slash() -> None:
    # Figma sometimes uses these in node names
    assert _to_component_name("Section: Header / Main") == "SectionHeaderMain"


def test_leading_digit_prefixed_with_f() -> None:
    # JS identifiers can't start with a digit — prefix with F
    assert _to_component_name("3 Column Layout") == "F3ColumnLayout"


def test_empty_falls_back() -> None:
    assert _to_component_name("") == "FigmaNode"


def test_only_special_chars_falls_back() -> None:
    # Nothing left after stripping non-identifier chars
    assert _to_component_name("---///:::") == "FigmaNode"


def test_length_cap() -> None:
    long = "A" * 80
    out = _to_component_name(long)
    assert len(out) == 60


def test_already_pascal_preserved() -> None:
    assert _to_component_name("MyComponent") == "MyComponent"
