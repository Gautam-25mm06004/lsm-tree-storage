# LSM-Tree Key-Value Storage Engine

A log-structured merge-tree store (the design behind LevelDB, RocksDB and Cassandra) in pure Python:

- **Write-ahead log** with a CRC32 per record; recovery replays complete records and truncates a torn tail.
- **Memtable** → flushed to immutable **SSTables** (4 KB data blocks, sparse block index, per-table **bloom filter**,
  footer), published atomically (write to temp file, fsync, rename).
- **Manifest** listing live tables, replaced atomically so a crash never exposes a half-finished flush or compaction.
- **Tombstones** for deletes, **k-way merge** for range scans and **size-tiered compaction** (newest version wins).

## Results

**Compaction is a trade between write and read amplification** (60,000 random writes, 100-byte values, 64 KB memtable)

| Compaction trigger | SSTables at end | Write amplification | Block reads per lookup (bloom on / off) | Lookup latency (bloom on / off) |
|---|---|---|---|---|
| 2 tables | 1 | 50.8× | 0.40 / 1.00 | 12 / 12 µs |
| 4 tables | 1 | 18.7× | 0.40 / 1.00 | 8 / 11 µs |
| 8 tables | 5 | 9.0× | 0.45 / 4.97 | 23 / 49 µs |
| never | 103 | **2.2×** | 1.24 / **81.1** | 165 / 919 µs |

- Compacting often keeps reads cheap but rewrites the data many times (51× at trigger 2); never compacting writes data only
  ~2× (WAL + one flush) but a lookup may touch every table.
- **Bloom filters rescue read amplification**: with 103 tables, block reads per lookup fall from 81 to 1.24, and for absent keys
  from 103 to 1.07 (about 1% false positives per table, as designed).

**Bloom filter accuracy matches theory** `(1 − e^(−kn/m))^k`: 0.83% measured vs 0.82% predicted at 10 bits/key; 0.044% vs 0.046% at 16.

**Durability has a price:** fsync on every write drops throughput from 615k to 4.4k writes/s (225 µs per write on this VM).
**Recovery** replays the WAL at about 0.7–0.9M records/s (200k records in 0.23 s).

**Tests:** model-based testing against a Python dict over 20,000 random puts/deletes/gets with flushes and compactions;
reopen after close; 20 simulated crashes that cut the WAL at a random byte — every complete record survives, nothing after
the cut appears, and new writes after recovery are durable.

Full tables: [`results/summary.md`](results/summary.md)

## Run
```bash
python -m unittest discover -s tests -v
python scripts/run_experiments.py     # ~1 min
```
```python
from lsm import LSMTree
db = LSMTree("data")
db.put(b"user:1", b"Gautam"); db.delete(b"user:2")
print(db.get(b"user:1"), db.scan(b"user:", b"user;"))
db.close()
```
