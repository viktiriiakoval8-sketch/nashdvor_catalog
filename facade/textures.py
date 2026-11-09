"""Offline runtime textures; network access is restricted to explicit preparation."""
import base64
import hashlib
import io
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000


def cache_path(source, cache):
    return Path(cache) / (hashlib.sha256(source.encode('utf-8')).hexdigest() + '.image')


def decode(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('Texture too large')
    with Image.open(io.BytesIO(raw)) as image:
        if image.width * image.height > MAX_PIXELS:
            raise ValueError('Texture has too many pixels')
        return image.convert('RGB')


def load(source, root, cache):
    if source.startswith('data:image/'):
        raw = base64.b64decode(source.split(',', 1)[1], validate=True)
    elif source.startswith('textures/'):
        path = (Path(root) / source).resolve()
        if not path.is_relative_to((Path(root) / 'textures').resolve()):
            raise ValueError('Invalid texture path')
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
    else:
        validate_remote(source)
        try:
            with cache_path(source, cache).open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
        except FileNotFoundError as exc:
            raise ValueError('Texture is not prepared; run tools/prepare_facade_textures.py') from exc
    return decode(raw)


def validate_remote(source):
    url = urlparse(source)
    if url.scheme != 'https' or url.hostname != 'nashdvor.com.ua' or url.username or url.password or url.port not in (None, 443):
        raise ValueError('Texture host is not allowed')


def prepare(source, root, cache, client):
    """Validate cached bytes first; replace missing/corrupt downloads atomically."""
    if source.startswith(('data:image/', 'textures/')):
        load(source, root, cache).close()
        return 'local'
    validate_remote(source)
    target = cache_path(source, cache)
    if target.exists():
        try:
            load(source, root, cache).close()
            return 'cached'
        except (OSError, ValueError):
            pass
    with client.stream('GET', source) as response:
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_bytes():
            raw.extend(chunk)
            if len(raw) > MAX_BYTES:
                raise ValueError('Texture too large')
    decode(bytes(raw)).close()
    target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.tmp', delete=False) as stream:
            name = stream.name
            stream.write(raw)
        os.replace(name, target)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()
    return 'downloaded'
