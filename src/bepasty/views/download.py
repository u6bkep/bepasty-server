import errno
from io import BytesIO
import os
import time

try:
    import PIL
except ImportError:
    # Pillow / PIL is optional
    PIL = None
else:
    from PIL import Image

try:
    import av  # for video thumbnail generation
except ImportError:
    # av is optional, used for video thumbnail generation
    av = None
else:
    from av import VideoFrame

from flask import Response, current_app, render_template, stream_with_context
from flask.views import MethodView
from werkzeug.exceptions import NotFound, Forbidden

from ..constants import COMPLETE, FILENAME, LOCKED, SIZE, TIMESTAMP_DOWNLOAD, TYPE
from ..utils.date_funcs import delete_if_lifetime_over
from ..utils.permissions import ADMIN, READ, may


class DownloadView(MethodView):
    content_disposition = 'attachment'  # to trigger download

    def err_incomplete(self, item, error):
        return render_template('error.html', heading=item.meta[FILENAME], body=error), 409

    def stream(self, item, start, limit):
        with item as _item:
            # Stream content from storage
            offset = max(0, start)
            while offset < limit:
                buf = _item.data.read(min(limit - offset, 16 * 1024), offset)
                offset += len(buf)
                yield buf
            item.meta[TIMESTAMP_DOWNLOAD] = int(time.time())

    def response(self, item, name):
        ct = item.meta[TYPE]
        dispo = self.content_disposition
        if dispo != 'attachment':
            # no simple download, so we must be careful about XSS
            if ct.startswith("text/"):
                ct = 'text/plain'  # only send simple plain text

        ret = Response(stream_with_context(self.stream(item, 0, item.data.size)))
        ret.headers['Content-Disposition'] = '{}; filename="{}"'.format(
            dispo, item.meta[FILENAME])
        ret.headers['Content-Length'] = item.meta[SIZE]
        ret.headers['Content-Type'] = ct
        ret.headers['X-Content-Type-Options'] = 'nosniff'  # yes, we really mean it
        # Cache headers - files never change
        ret.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        ret.headers['ETag'] = f'"{name}"'
        return ret

    def get(self, name):
        if not may(READ):
            raise Forbidden()
        try:
            item = current_app.storage.openwrite(name)
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise NotFound()
            raise

        try:
            need_close = True
            if not item.meta[COMPLETE]:
                return self.err_incomplete(item, 'Upload incomplete. Try again later.')

            if item.meta[LOCKED] and not may(ADMIN):
                raise Forbidden()

            if delete_if_lifetime_over(item, name):
                raise NotFound()
            need_close = False
        finally:
            if need_close:
                item.close()

        return self.response(item, name)


class InlineView(DownloadView):
    content_disposition = 'inline'  # to trigger viewing in browser, for some types


class ThumbnailView(InlineView):
    thumbnail_size = 192, 108

    def _generate_placeholder_thumbnail(self, mimetype):
        """Generate a placeholder thumbnail SVG with the mimetype displayed."""
        return f"""\
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg width="108" height="108" viewBox="0 0 108 108" xmlns="http://www.w3.org/2000/svg">
<rect x="1" y="1" width="106" height="106" fill="whitesmoke" stroke-width="2" stroke="blue" />
    <line x1="1" y1="1" x2="106" y2="106" stroke="blue" stroke-width="2" />
    <line x1="1" y1="106" x2="106" y2="0" stroke="blue" stroke-width="2" />
    <rect x="10" y="40" width="88" height="24" fill="whitesmoke" fill-opacity="0.9"/>
    <text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" font-family="Arial, sans-serif" font-size="18" fill="blue" lengthAdjust="spacingAndGlyphs" textLength="90">{mimetype}</text>

</svg>""".strip().encode()

    def err_incomplete(self, item, error):
        return b'', 409  # conflict

    def _generate_image_thumbnail(self, item, sz, thumbnail_type):
        """Generate thumbnail data for supported image types."""
        with BytesIO(item.data.read(sz, 0)) as img_bio, BytesIO() as thumbnail_bio:
            with Image.open(img_bio) as img:
                img.thumbnail(self.thumbnail_size)
                img.save(thumbnail_bio, thumbnail_type)
            return thumbnail_bio.getvalue()
    def _generate_video_thumbnail(self, item, sz):
        """Generate thumbnail data for video types."""
        with BytesIO(item.data.read(sz, 0)) as video_bio, BytesIO() as thumbnail_bio:
            container = av.open(video_bio)
            stream = container.streams.video[0]
            frame = next(container.decode(stream))
            frame = frame.to_image()
            frame.thumbnail(self.thumbnail_size)
            frame.save(thumbnail_bio, 'jpeg')
            return thumbnail_bio.getvalue()
    def _generate_txt_thumbnail(self, item, sz):
        """Generate a thumbnail for text files."""
        with BytesIO(item.data.read(min(sz, 1024), 0)) as txt_bio:
            content = txt_bio.read().decode('utf-8', errors='replace')
            # Take first few lines and limit characters
            lines = content.split('\n')[:6]
            preview_text = '\n'.join(line[:30] + ('...' if len(line) > 30 else '') for line in lines)
            
            # Escape XML special characters
            preview_text = preview_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            return f"""\
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg width="108" height="108" viewBox="0 0 108 108" xmlns="http://www.w3.org/2000/svg">
<rect x="1" y="1" width="106" height="106" fill="white" stroke-width="2" stroke="gray" />
<foreignObject x="4" y="4" width="100" height="100">
<div xmlns="http://www.w3.org/1999/xhtml" style="font-family: monospace; font-size: 8px; line-height: 1.2; overflow: hidden; white-space: pre-wrap; word-wrap: break-word;">
{preview_text}
</div>
</foreignObject>
</svg>""".strip().encode()

    def response(self, item, name):
        sz = item.meta[SIZE]
        fn = item.meta[FILENAME]
        ct = item.meta[TYPE]
        if not PIL:
            # return a placeholder thumbnail for unsupported item types
            thumbnail_data = self._generate_placeholder_thumbnail(ct)
            ret = Response(thumbnail_data)
            ret.headers['Content-Length'] = len(thumbnail_data)
            ret.headers['Content-Type'] = 'image/svg+xml'
            ret.headers['X-Content-Type-Options'] = 'nosniff'
            ret.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            ret.headers['ETag'] = f'"{name}-thumb"'
            return ret

        match ct:
            case 'image/jpeg':
                thumbnail_type = 'jpeg'
                thumbnail_data = self._generate_image_thumbnail(item, sz, thumbnail_type)
            case 'image/png' | 'image/gif':
                thumbnail_type = 'png'
                thumbnail_data = self._generate_image_thumbnail(item, sz, thumbnail_type)
            case 'image/webp':
                thumbnail_type = 'webp'
                thumbnail_data = self._generate_image_thumbnail(item, sz, thumbnail_type)
            case 'image/bmp':
                thumbnail_type = 'bmp'
                thumbnail_data = self._generate_image_thumbnail(item, sz, thumbnail_type)
            case 'image/svg+xml':
                thumbnail_type = 'svg+xml'
                # Return SVG directly without processing
                thumbnail_data = item.data.read(sz, 0)
            case 'video/mp4':
                thumbnail_type = 'mp4'
                thumbnail_data = self._generate_video_thumbnail(item, sz)
            case ct if ct.startswith('text/'):
                thumbnail_type = 'svg+xml'
                thumbnail_data = self._generate_txt_thumbnail(item, sz)
            case _:
                # return a placeholder thumbnail for unsupported item types
                thumbnail_data = self._generate_placeholder_thumbnail(ct)
                ret = Response(thumbnail_data)
                ret.headers['Content-Length'] = len(thumbnail_data)
                ret.headers['Content-Type'] = 'image/svg+xml'
                ret.headers['X-Content-Type-Options'] = 'nosniff'  # yes, we really mean it
                ret.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
                ret.headers['ETag'] = f'"{name}-thumb"'
                return ret

        name, ext = os.path.splitext(fn)
        thumbnail_fn = '{}-thumb.{}'.format(name, thumbnail_type)

        ret = Response(thumbnail_data)
        ret.headers['Content-Disposition'] = '{}; filename="{}"'.format(
            self.content_disposition, thumbnail_fn)
        ret.headers['Content-Length'] = len(thumbnail_data)
        ret.headers['Content-Type'] = 'image/%s' % thumbnail_type
        ret.headers['X-Content-Type-Options'] = 'nosniff'  # yes, we really mean it
        # Cache headers - thumbnails never change
        ret.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        ret.headers['ETag'] = f'"{name}-thumb"'
        return ret
