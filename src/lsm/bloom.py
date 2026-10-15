import hashlib, math


class BloomFilter:
    """k hash functions derived from two 64-bit halves of BLAKE2b (Kirsch-Mitzenmacher double hashing)."""
    def __init__(self, n_items, fp_rate=0.01, bits=None, k=None):
        self.m = bits or max(64, int(-n_items * math.log(fp_rate) / math.log(2) ** 2))
        self.k = k or max(1, round(self.m / max(1, n_items) * math.log(2)))
        self.bits = bytearray((self.m + 7) // 8)

    def _hashes(self, key: bytes):
        h = hashlib.blake2b(key, digest_size=16).digest()
        a, b = int.from_bytes(h[:8], "little"), int.from_bytes(h[8:], "little") | 1
        return ((a + i * b) % self.m for i in range(self.k))

    def add(self, key: bytes):
        for h in self._hashes(key):
            self.bits[h >> 3] |= 1 << (h & 7)

    def __contains__(self, key: bytes):
        return all(self.bits[h >> 3] >> (h & 7) & 1 for h in self._hashes(key))

    def to_bytes(self):
        return self.m.to_bytes(8, "little") + self.k.to_bytes(2, "little") + bytes(self.bits)

    @classmethod
    def from_bytes(cls, b):
        f = cls.__new__(cls)
        f.m, f.k = int.from_bytes(b[:8], "little"), int.from_bytes(b[8:10], "little")
        f.bits = bytearray(b[10:])
        return f
