import random


# Return a random string of 6 letter/digits.
def random_token(length=6) -> str:
    return "".join(
        [random.choice('0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ') for x in range(length)])
