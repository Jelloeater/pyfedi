import random
from unicodedata import normalize


# Return a random string of 6 letter/digits.
def random_token(length=6) -> str:
    return "".join(
        [random.choice('0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ') for x in range(length)])


def normalize_utf(username):
    return normalize('NFKC', username)
