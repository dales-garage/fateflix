"""Scoped NNTP credential names and validation; contains no secret values."""

KEYS = {
    'NGD_USERNAME': 'NGD_USERNAME',
    'NGD_PASSWORD': 'NGD_PASSWORD',
    'USENET_FARM_USERNAME': 'USENET_FARM_USERNAME',
    'USENET_FARM_PASSWORD': 'USENET_FARM_PASSWORD',
    'VIPERNEWS_USERNAME': 'VIPERNEWS_USERNAME',
    'VIPERNEWS_PASSWORD': 'VIPERNEWS_PASSWORD',
    'SUPERNEWS_USERNAME': 'SUPERNEWS_USERNAME',
    'SUPERNEWS_PASSWORD': 'SUPERNEWS_PASSWORD',
    'EWEKA_USERNAME': 'EWEKA_USERNAME',
    'EWEKA_PASSWORD': 'EWEKA_PASSWORD',
}


def validate(values):
    if set(values) != set(KEYS) or any(
        not isinstance(value, str) or not value or len(value) > 4096
        or any(character in value for character in ("\x00", "\n", "\r"))
        for value in values.values()
    ):
        raise ValueError("Missing or invalid NNTP credentials")
