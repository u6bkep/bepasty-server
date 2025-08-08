import errno
import pickle

from flask import current_app, render_template
from flask.views import MethodView
from werkzeug.exceptions import Forbidden

from ..constants import ID, SIZE, TIMESTAMP_UPLOAD
from ..utils.date_funcs import delete_if_lifetime_over
from ..utils.permissions import LIST, may

def sizeof_fmt(num, suffix="B"):
    for unit in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"


def file_infos(names=None):
    """
    iterates over storage files metadata.
    note: we put the storage name into the metadata as ID

    :param names: None means "all items"
                  otherwise give a list of storage item names
    """
    storage = current_app.storage
    if names is None:
        names = list(storage)
    for name in names:
        try:
            with storage.open(name) as item:
                meta = dict(item.meta)
                if not meta:
                    # we got empty metadata, this happens for 0-byte .meta files.
                    # ignore it for now.
                    continue
                if delete_if_lifetime_over(item, name):
                    continue
                # convert size to human redable
                meta[SIZE] = sizeof_fmt(meta[SIZE])
                meta[ID] = name
                yield meta
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
        except pickle.UnpicklingError:
            # corrupted meta file, just ignore it for now
            pass


class FileListView(MethodView):
    def get(self):
        if not may(LIST):
            raise Forbidden()
        files = sorted(file_infos(), key=lambda f: f[TIMESTAMP_UPLOAD], reverse=True)
        return render_template('filelist.html', files=files)
