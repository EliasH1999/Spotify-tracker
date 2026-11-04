"""Keep external music metadata readable on a single terminal line."""
import re


def one_line(text):
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", text)
