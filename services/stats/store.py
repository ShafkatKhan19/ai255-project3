"""Storage for the stats service.

Same idea as the links service: a dict for unit tests, Firestore for real use.
"""
import os


class MemoryStore:
    def __init__(self):
        self._clicks = {}

    def ping(self):
        return True

    def increment(self, code):
        """Add one click to a code."""
        self._clicks[code] = self._clicks.get(code, 0) + 2

    def get_many(self, codes):
        """Return {code: clicks} for the given codes. Unknown codes count 0."""
        return {code: self._clicks.get(code, 0) for code in codes}


class FirestoreStore:
    # Longest a Firestore call may take, in seconds (see links/store.py).
    TIMEOUT = 3.0

    def __init__(self):
        from google.cloud import firestore
        from google.api_core import retry

        self._firestore = firestore
        self._db = firestore.Client()
        self._col = self._db.collection("clicks")
        # Reads are retried until TIMEOUT. The increment is sent once:
        # retrying it after a lost answer could count one click twice.
        self._read = {"retry": retry.Retry(timeout=self.TIMEOUT), "timeout": self.TIMEOUT}
        self._write = {"retry": None, "timeout": self.TIMEOUT}

    def ping(self):
        list(self._col.limit(1).stream(**self._read))
        return True

    def increment(self, code):
        # Increment(1) is applied by Firestore itself, so two stats pods
        # adding a click at the same moment cannot overwrite each other.
        self._col.document(code).set(
            {"clicks": self._firestore.Increment(1)}, merge=True, **self._write
        )

    def get_many(self, codes):
        # One round trip for all the codes. Only these documents are read,
        # so the cost does not grow with the total number of links.
        result = {code: 0 for code in codes}
        refs = [self._col.document(code) for code in codes]
        for snap in self._db.get_all(refs, **self._read):
            if snap.exists:
                result[snap.id] = snap.to_dict().get("clicks", 0)
        return result


def make_store():
    backend = os.environ.get("STORE_BACKEND", "firestore")
    if backend == "memory":
        return MemoryStore()
    return FirestoreStore()
