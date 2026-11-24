"""Validation for strings persisted in UTF-8 PostgreSQL text fields."""

from typing import Annotated

from pydantic import AfterValidator


def validate_database_text(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Text contains a null character")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Text contains invalid Unicode") from None
    return value


DatabaseText = Annotated[str, AfterValidator(validate_database_text)]
