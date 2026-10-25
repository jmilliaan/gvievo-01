"""agv_core.fsio: the durable-write primitives the revision stores share (lean plan D17)."""
import hashlib
import os
import tempfile
import threading
import time

from helpers import check

from agv_core import fsio


def test_fsio():
    print("\nfsio: writer lock, sha, positive revision, publish by rename")
    with tempfile.TemporaryDirectory() as root:
        order = []

        def writer(tag):
            with fsio.writer_lock(root):
                order.append(f"{tag}+")
                time.sleep(0.05)
                order.append(f"{tag}-")

        ts = [threading.Thread(target=writer, args=(k,)) for k in "ab"]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        check("two threads of one process exclude each other",
              order in (["a+", "a-", "b+", "b-"], ["b+", "b-", "a+", "a-"]), str(order))

        open(os.path.join(root, ".tmp-left"), "w").close()
        with fsio.writer_lock(root, sweep_prefix=".tmp-"):
            swept = not os.path.exists(os.path.join(root, ".tmp-left"))
        check("the lock sweeps abandoned temp files", swept)

        blob = os.urandom(3 << 20)  # spans several read chunks
        path = os.path.join(root, "blob")
        with open(path, "wb") as fh:
            fh.write(blob)
        check("chunked sha256 equals hashlib over the whole file",
              fsio.sha256_file(path) == hashlib.sha256(blob).hexdigest())

        bad = []
        for rev in (0, -1, True, 1.0, "1"):
            try:
                fsio.positive_revision(rev, KeyError)
            except KeyError:
                bad.append(rev)
        check("positive_revision refuses 0, negatives, bools, floats and strings in the store's error",
              len(bad) == 5 and fsio.positive_revision(3) == 3, str(bad))

        stage = tempfile.mkdtemp(prefix=".staging-", dir=root)
        with open(os.path.join(stage, "f"), "w") as fh:
            fh.write("x")
        dest = os.path.join(root, "rev1")
        fsio.publish_dir(stage, dest)
        stage2 = tempfile.mkdtemp(prefix=".staging-", dir=root)
        try:
            fsio.publish_dir(stage2, dest)
            refused = False
        except FileExistsError:
            refused = True
        check("publish renames the stage and refuses an existing revision",
              os.path.isfile(os.path.join(dest, "f")) and not os.path.exists(stage) and refused
              and os.path.isdir(stage2))
        try:
            fsio.publish_dir(stage2, os.path.join(root, "missing", "rev2"),
                             wrap=lambda e: KeyError(str(e)))
            wrapped = False
        except KeyError:
            wrapped = True
        check("a failed rename is re-raised as the store's own error", wrapped)


TESTS = [test_fsio]
