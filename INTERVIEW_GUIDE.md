# Interview guide — LSM-tree storage engine

## 30-second version
"I built an LSM-tree key-value store like a mini LevelDB: writes go to a checksummed write-ahead log and a memtable, which is
flushed into immutable sorted files with a block index and a bloom filter; compaction merges them. I tested it against a
Python dict on 20,000 random operations and simulated crashes by cutting the log at random bytes. The experiments show the core
trade-off: compacting often costs 51× write amplification, never compacting makes lookups touch 81 files — unless you have bloom
filters, which bring that down to about 1."

## Must-know
- **Why LSM**: turn random writes into sequential ones (append to log, flush sorted files). Great for write-heavy workloads.
- **WAL**: makes the memtable durable; CRC detects a torn last record after a crash.
- **SSTable**: sorted, immutable; index of first key per block → one disk read per lookup.
- **Bloom filter**: "definitely not here" or "maybe here"; ~1% false positives at ~10 bits per key.
- **Compaction**: merge files, keep newest version, drop deleted keys. Controls read and space amplification at the cost of
  write amplification.
- **Atomic rename + manifest**: crash-consistent metadata updates.
- **Amplification**: write amp = bytes written to disk ÷ bytes written by the user; read amp = disk reads per lookup.

## Likely questions
1. *Why can tombstones only be dropped in a full merge?* An older table not included in the merge might still hold the key;
   dropping the tombstone would resurrect it.
2. *LSM vs B-tree?* LSM: faster writes, more read and write amplification; B-tree: in-place updates, faster point reads.
3. *Size-tiered vs leveled?* Leveled bounds the number of files per lookup and space amplification but rewrites more.
4. *How to make fsync cheaper?* Group commit — batch many writes per fsync.
