"""LSM experiments: bloom filter accuracy vs theory, read amplification with/without bloom filters, the compaction
trade-off (write vs read amplification), durability cost of fsync, and recovery time."""
import json, math, os, random, shutil, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lsm import LSMTree, BloomFilter  # noqa

R = {}
rng = random.Random(0)

# 1) Bloom filter: measured vs theoretical false-positive rate
bl = []
n = 20000
for bits_per_key in (4, 6, 8, 10, 12, 16):
    m = bits_per_key * n
    k = max(1, round(bits_per_key * math.log(2)))
    b = BloomFilter(n, bits=m, k=k)
    for i in range(n):
        b.add(f"in{i}".encode())
    fp = sum(f"out{i}".encode() in b for i in range(50000)) / 50000
    bl.append({"bits_per_key": bits_per_key, "hashes": k, "measured_fp_%": round(100 * fp, 3),
               "theory_fp_%": round(100 * (1 - math.exp(-k * n / m)) ** k, 3)})
R["bloom"] = bl

def load(d, n_keys, trigger, bloom=True, value_len=100, seed=0, mem=64 << 10):
    r = random.Random(seed)
    db = LSMTree(d, memtable_bytes=mem, compaction_trigger=trigger, bloom=bloom)
    t = time.perf_counter()
    for i in range(n_keys):
        k = f"user{r.randrange(n_keys * 2):08d}".encode()
        db.put(k, os.urandom(value_len))
    return db, time.perf_counter() - t

# 2) + 3) Compaction policy vs read/write amplification
comp = []
for trig in (2, 4, 8, 10 ** 9):
    for bloom in (True, False):
        d = tempfile.mkdtemp()
        db, wt = load(d, 60000, trig, bloom)
        db.flush()
        tables = len(db.tables)
        wa = (db.stats["wal_bytes"] + db.stats["sst_bytes"]) / db.stats["user_bytes"]
        before = db.block_reads()
        r2 = random.Random(9)
        t = time.perf_counter()
        for _ in range(5000):
            db.get(f"user{r2.randrange(120000):08d}".encode())        # ~half the keys exist
        lt = (time.perf_counter() - t) / 5000
        reads = (db.block_reads() - before) / 5000
        before = db.block_reads()
        for _ in range(3000):
            db.get(f"user{r2.randrange(120000):08d}~".encode())   # absent, but inside the key range: needs a block read without bloom
        miss_reads = (db.block_reads() - before) / 3000
        comp.append({"compaction_trigger": "never" if trig > 1e6 else trig, "bloom": bloom, "sstables": tables,
                     "write_amplification": round(wa, 2), "write_kops_per_s": round(60000 / wt / 1000, 1),
                     "block_reads_per_get": round(reads, 2), "block_reads_per_missing_get": round(miss_reads, 3),
                     "get_latency_us": round(lt * 1e6, 1)})
        db.close(); shutil.rmtree(d)
R["compaction"] = comp

# 4) Durability: cost of fsync on every write
dur = []
for sync in (False, True):
    d = tempfile.mkdtemp()
    db = LSMTree(d, sync=sync, memtable_bytes=1 << 30)
    t = time.perf_counter()
    N = 3000
    for i in range(N):
        db.put(f"k{i}".encode(), b"x" * 100)
    el = time.perf_counter() - t
    dur.append({"fsync_every_write": sync, "writes_per_s": round(N / el), "mean_latency_us": round(el / N * 1e6, 1)})
    db.close(); shutil.rmtree(d)
R["durability"] = dur

# 5) Recovery time vs WAL size
rec = []
for N in (10000, 50000, 200000):
    d = tempfile.mkdtemp()
    db = LSMTree(d, memtable_bytes=1 << 34)
    for i in range(N):
        db.put(f"k{i:09d}".encode(), b"v" * 50)
    db.close()
    t = time.perf_counter(); db2 = LSMTree(d, memtable_bytes=1 << 34); el = time.perf_counter() - t
    rec.append({"wal_records": N, "wal_MB": round(os.path.getsize(db2._wal_path()) / 1e6, 1), "recovery_s": round(el, 3),
                "records_per_s": round(N / el)})
    db2.close(); shutil.rmtree(d)
R["recovery"] = rec

(ROOT / "results" / "results.json").write_text(json.dumps(R, indent=2))
def tbl(rows):
    cols = list(rows[0]); return "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n" + "".join("| " + " | ".join(str(r[c]) for c in cols) + " |\n" for r in rows)
md = "# Results\n\n## Bloom filter false-positive rate (20,000 keys, 50,000 negative probes)\n\n" + tbl(bl)
md += "\n## Compaction trade-off (60,000 random writes of 100-byte values, 64 KB memtable; 5,000 lookups)\n\n" + tbl(comp)
md += "\n## Durability cost\n\n" + tbl(dur) + "\n## Recovery (WAL replay)\n\n" + tbl(rec)
(ROOT / "results" / "summary.md").write_text(md)
print(md)
