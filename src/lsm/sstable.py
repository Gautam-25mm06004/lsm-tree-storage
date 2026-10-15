"""Immutable sorted string table.

File layout:  [data blocks][index][bloom][footer]
  record   = key_len u32 | val_len u32 (0xFFFFFFFF = tombstone) | key | value
  index    = for every block: first_key_len u32 | first_key | offset u64 | length u32
  footer   = index_off u64 | index_len u32 | bloom_off u64 | bloom_len u32 | n_records u64 | magic 'LSMT'
Reads load only the index and bloom filter into memory; a lookup reads at most one data block from disk.
"""
import bisect, os, struct
from .bloom import BloomFilter

TOMB = 0xFFFFFFFF
MAGIC = b"LSMT"
FOOTER = struct.Struct("<QIQIQ4s")


def write_sstable(path, items, block_size=4096, bloom_fp=0.01):
    """items: sorted iterable of (key: bytes, value: bytes | None). None = tombstone."""
    items = list(items)
    bloom = BloomFilter(len(items), bloom_fp)
    index, buf, first, off = [], bytearray(), None, 0
    with open(path + ".tmp", "wb") as f:
        def flush_block():
            nonlocal buf, first, off
            if buf:
                f.write(buf); index.append((first, off, len(buf))); off += len(buf); buf, first = bytearray(), None
        for k, v in items:
            bloom.add(k)
            if first is None:
                first = k
            buf += struct.pack("<II", len(k), TOMB if v is None else len(v)) + k + (v or b"")
            if len(buf) >= block_size:
                flush_block()
        flush_block()
        idx = bytearray()
        for k, o, n in index:
            idx += struct.pack("<I", len(k)) + k + struct.pack("<QI", o, n)
        f.write(idx)
        bl = bloom.to_bytes()
        f.write(bl)
        f.write(FOOTER.pack(off, len(idx), off + len(idx), len(bl), len(items), MAGIC))
        f.flush(); os.fsync(f.fileno())
    os.replace(path + ".tmp", path)          # atomic publish: readers never see a half-written table


class SSTable:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        self.f.seek(-FOOTER.size, os.SEEK_END)
        io, il, bo, bl, self.n, magic = FOOTER.unpack(self.f.read(FOOTER.size))
        if magic != MAGIC:
            raise IOError(f"corrupt sstable {path}")
        self.f.seek(io); raw = self.f.read(il)
        self.keys, self.blocks, p = [], [], 0
        while p < len(raw):
            (kl,) = struct.unpack_from("<I", raw, p); p += 4
            k = raw[p:p + kl]; p += kl
            o, n = struct.unpack_from("<QI", raw, p); p += 12
            self.keys.append(k); self.blocks.append((o, n))
        self.f.seek(bo); self.bloom = BloomFilter.from_bytes(self.f.read(bl))
        self.block_reads = 0

    def _block(self, i):
        o, n = self.blocks[i]
        self.f.seek(o); self.block_reads += 1
        return self.f.read(n)

    @staticmethod
    def _records(block):
        p = 0
        while p < len(block):
            kl, vl = struct.unpack_from("<II", block, p); p += 8
            k = block[p:p + kl]; p += kl
            if vl == TOMB:
                yield k, None
            else:
                yield k, block[p:p + vl]; p += vl

    def get(self, key, use_bloom=True):
        """Returns (found, value). value None with found=True means tombstone."""
        if use_bloom and key not in self.bloom:
            return False, None
        i = bisect.bisect_right(self.keys, key) - 1
        if i < 0:
            return False, None
        for k, v in self._records(self._block(i)):
            if k == key:
                return True, v
            if k > key:
                break
        return False, None

    def items(self):
        for i in range(len(self.blocks)):
            yield from self._records(self._block(i))

    def close(self):
        self.f.close()
