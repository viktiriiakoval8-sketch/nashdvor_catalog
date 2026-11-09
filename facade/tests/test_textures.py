import io
import base64

import pytest
from PIL import Image

from facade import textures

URL = 'https://nashdvor.com.ua/texture.png'


def png():
    out = io.BytesIO()
    Image.new('RGB', (12, 8), 'red').save(out, 'PNG')
    return out.getvalue()


class Client:
    def __init__(self, raw):
        self.raw, self.calls = raw, 0

    def stream(self, method, url):
        self.calls += 1
        return self

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def raise_for_status(self): pass
    def iter_bytes(self): yield self.raw


def test_preparation_is_reused_and_runtime_is_offline(tmp_path):
    client = Client(png())
    assert textures.prepare(URL, tmp_path, tmp_path, client) == 'downloaded'
    assert textures.prepare(URL, tmp_path, tmp_path, client) == 'cached'
    assert client.calls == 1
    with textures.load(URL, tmp_path, tmp_path) as image:
        assert image.size == (12, 8)
    with pytest.raises(ValueError, match='not prepared'):
        textures.load(URL + '?new-version', tmp_path, tmp_path)


def test_invalid_download_is_never_cached_and_corrupt_cache_recovers(tmp_path):
    with pytest.raises(OSError):
        textures.prepare(URL, tmp_path, tmp_path, Client(b'not an image'))
    target = textures.cache_path(URL, tmp_path)
    assert not target.exists()
    target.write_bytes(b'broken')
    assert textures.prepare(URL, tmp_path, tmp_path, Client(png())) == 'downloaded'
    assert not list(tmp_path.glob('*.tmp'))


def test_embedded_and_local_sources_and_size_limits(tmp_path, monkeypatch):
    raw = png()
    source = 'data:image/png;base64,' + base64.b64encode(raw).decode()
    assert textures.load(source, tmp_path, tmp_path).size == (12, 8)
    (tmp_path / 'textures').mkdir()
    (tmp_path / 'textures/a.png').write_bytes(raw)
    assert textures.load('textures/a.png', tmp_path, tmp_path).size == (12, 8)
    with pytest.raises(ValueError, match='Invalid texture path'):
        textures.load('textures/../secret', tmp_path, tmp_path)
    monkeypatch.setattr(textures, 'MAX_BYTES', 5)
    with pytest.raises(ValueError, match='too large'):
        textures.prepare(URL, tmp_path, tmp_path, Client(raw))
    assert not textures.cache_path(URL, tmp_path).exists()


@pytest.mark.parametrize('source', ['http://nashdvor.com.ua/x', 'https://example.com/x', 'https://nashdvor.com.ua:444/x', 'https://user@nashdvor.com.ua/x'])
def test_unapproved_sources_never_download(tmp_path, source):
    client = Client(png())
    with pytest.raises(ValueError):
        textures.prepare(source, tmp_path, tmp_path, client)
    assert client.calls == 0
