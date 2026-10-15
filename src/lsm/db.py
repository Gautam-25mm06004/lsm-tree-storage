"""LSM-tree key-value store: write-ahead log -> memtable -> immutable SSTables, size-tiered compaction,
atomic manifest, crash recovery that tolerates a torn final WAL record."""
import heapq, json, os, struct, zlib
from .sstable import SSTable, write_sstable

PUT, DEL = 1, 2
REC = struct.Struct("<IIB")     # crc32, payload length, op


class LSMTree:
    def __init__(self, path, memtable_bytes=1 << 20, compaction_trigger=4, sync=False, bloom=True, block_size=4096):
        self.path, self.limit, self.trigger, self.sync, self.use_bloom, self.block_size = path, memtable_bytes, compaction_trigger, sync, bloom, block_size
        os.makedirs(path, exist_ok=True)
        self.stats = {"user_bytes": 0, "wal_bytes": 0, "sst_bytes": 0, "flushes": 0, "compactions": 0, "recovered_records": 0, "torn_tail_bytes": 0}
        self._load_manifest()
        self.mem, self.mem_bytes = {}, 0
        self._recover()
        self.wal = open(self._wal_path(), "ab")

    # ---- files ----
    def _wal_path(self):
        return os.path.join(self.path, f"wal-{self.wal_id:06d}.log")

    def _load_manifest(self):
        mp = os.path.join(self.path, "MANIFEST")
        if os.path.exists(mp):
            m = json.load(open(mp))
        else:
            m = {"tables": [], "next_id": 1, "wal_id": 1}
        self.next_id, self.wal_id = m["next_id"], m["wal_id"]
        self.tables = [SSTable(os.path.join(self.path, t)) for t in m["tables"]]   # newest first

    def _save_manifest(self):
        m = {"tables": [os.path.basename(t.path) for t in self.tables], "next_id": self.next_id, "wal_id": self.wal_id}
        tmp = os.path.join(self.path, "MANIFEST.tmp")
        with open(tmp, "w") as f:
            json.dump(m, f); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, os.path.join(self.path, "MANIFEST"))

    # ---- recovery ----
    def _recover(self):
        p = self._wal_path()
        if not os.path.exists(p):
            return
        data = open(p, "rb").read()
        off = 0
        while off + REC.size <= len(data):
            crc, n, op = REC.unpack_from(data, off)
            payload = data[off + REC.size: off + REC.size + n]
            if len(payload) < n or zlib.crc32(bytes([op]) + payload) != crc:
                break                                   # torn or corrupt tail: stop replay here
            (kl,) = struct.unpack_from("<I", payload, 0)
            k, v = payload[4:4 + kl], payload[4 + kl:]
            self._apply(op, k, v)
            self.stats["recovered_records"] += 1
            off += REC.size + n
        self.stats["torn_tail_bytes"] = len(data) - off
        if off < len(data):                              # drop the torn tail so new appends start clean
            with open(p, "r+b") as f:
                f.truncate(off)

    def _apply(self, op, k, v):
        old = self.mem.get(k, b"")
        self.mem[k] = v if op == PUT else None
        self.mem_bytes += len(k) + len(v or b"") - (len(old) if old else 0)

    # ---- writes ----
    def _log(self, op, k, v=b""):
        payload = struct.pack("<I", len(k)) + k + v
        rec = REC.pack(zlib.crc32(bytes([op]) + payload), len(payload), op) + payload
        self.wal.write(rec)
        if self.sync:
            self.wal.flush(); os.fsync(self.wal.fileno())
        self.stats["wal_bytes"] += len(rec)

    def put(self, k: bytes, v: bytes):
        self.stats["user_bytes"] += len(k) + len(v)
        self._log(PUT, k, v); self._apply(PUT, k, v)
        if self.mem_bytes >= self.limit:
            self.flush()

    def delete(self, k: bytes):
        self._log(DEL, k); self._apply(DEL, k, b"")
        if self.mem_bytes >= self.limit:
            self.flush()

    def flush(self):
        if not self.mem:
            return
        self.wal.flush()
        name = f"sst-{self.next_id:06d}.sst"; self.next_id += 1
        path = os.path.join(self.path, name)
        write_sstable(path, sorted(self.mem.items()), self.block_size)
        self.stats["sst_bytes"] += os.path.getsize(path); self.stats["flushes"] += 1
        self.tables.insert(0, SSTable(path))
        old_wal = self._wal_path()
        self.wal.close()
        self.wal_id += 1
        self._save_manifest()                           # new table + new WAL become visible atomically
        os.remove(old_wal)
        self.wal = open(self._wal_path(), "ab")
        self.mem, self.mem_bytes = {}, 0
        if len(self.tables) >= self.trigger:
            self.compact()

    def compact(self):
        """Size-tiered: merge all tables into one; newest version wins; tombstones dropped (merging into the last level)."""
        merged = self._merge([t.items() for t in self.tables], drop_tombstones=True)
        name = f"sst-{self.next_id:06d}.sst"; self.next_id += 1
        path = os.path.join(self.path, name)
        write_sstable(path, merged, self.block_size)
        self.stats["sst_bytes"] += os.path.getsize(path); self.stats["compactions"] += 1
        old = self.tables
        self.tables = [SSTable(path)]
        self._save_manifest()
        for t in old:
            t.close(); os.remove(t.path)

    @staticmethod
    def _merge(sources, drop_tombstones=False):
        """k-way merge of sorted (key, value) streams; sources[0] is newest."""
        heap = []
        its = [iter(s) for s in sources]
        for i, it in enumerate(its):
            for k, v in it:
                heap.append((k, i, v)); break
        heapq.heapify(heap)
        last = None
        while heap:
            k, i, v = heapq.heappop(heap)
            nxt = next(its[i], None)
            if nxt is not None:
                heapq.heappush(heap, (nxt[0], i, nxt[1]))
            if k == last:
                continue                                # an older version of a key we've already emitted
            last = k
            if v is None and drop_tombstones:
                continue
            yield k, v

    # ---- reads ----
    def get(self, k: bytes):
        if k in self.mem:
            return self.mem[k]
        for t in self.tables:
            found, v = t.get(k, self.use_bloom)
            if found:
                return v
        return None

    def scan(self, lo: bytes, hi: bytes):
        mem = sorted((k, v) for k, v in self.mem.items() if lo <= k < hi)
        srcs = [mem] + [((k, v) for k, v in t.items() if lo <= k < hi) for t in self.tables]
        return [(k, v) for k, v in self._merge(srcs) if v is not None]

    def block_reads(self):
        return sum(t.block_reads for t in self.tables)

    def close(self):
        self.wal.flush(); self.wal.close()
        for t in self.tables:
            t.close()
