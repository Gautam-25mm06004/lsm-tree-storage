# An LSM-Tree Storage Engine: Crash Safety and the Read/Write Amplification Trade-off

**Gautam Jain** — IIT Bhubaneswar

## 1. Design
Writes append to a write-ahead log (WAL) and update an in-memory table; when the memtable exceeds a size limit it is written
out as a sorted, immutable SSTable and the WAL is rotated. Reads check the memtable and then SSTables from newest to oldest.
Deletes write tombstones. Compaction merges SSTables into one, keeping the newest version of each key and dropping tombstones
(safe because the merge covers all tables).

**SSTable format.** Records `key_len | val_len | key | value` packed into ~4 KB blocks; an index holds each block's first
key and offset; a bloom filter covers all keys; a fixed-size footer locates index and filter and carries a magic number. A
lookup consults the filter, binary-searches the index and reads one block.

**Crash safety.** Each WAL record carries CRC32(op ‖ payload) and a length; recovery stops at the first incomplete or
corrupt record and truncates the file there. SSTables are written to a temporary file, fsynced and renamed. The manifest
(list of live tables, next WAL id) is replaced atomically after a flush or compaction, and only then is the old WAL or
old tables deleted — so at any crash point the on-disk state is either the old or the new version.

## 2. Bloom filters
With m bits, n keys and k = (m/n)·ln 2 hash functions, the false-positive rate is about `(1 − e^{−kn/m})^k`. Hashes come from
one BLAKE2b digest split into two 64-bit values combined as `h₁ + i·h₂` (Kirsch & Mitzenmacher 2006). Measured rates match
the formula within sampling error from 4 to 16 bits per key.

## 3. Experiments
See README. Size-tiered compaction with a trigger of T tables rewrites each byte about once per merge it participates in;
smaller T means more merges and higher write amplification (51× at T = 2 vs 9× at T = 8) but fewer tables to search. Without
compaction, lookups without bloom filters read one block per table (81 on average for present keys with 103 tables); bloom
filters reduce this to ~1 + 1% × tables.

## 4. Limitations
Single-threaded, full-merge size-tiered compaction (no levels), no block cache or compression, Python-level performance. A
leveled design (as in LevelDB) would bound space and read amplification with lower write amplification for large data sets.

## References
1. P. O'Neil, E. Cheng, D. Gawlick, E. O'Neil. The log-structured merge-tree (LSM-tree). *Acta Informatica* 33(4), 351–385, 1996.
2. F. Chang et al. Bigtable: a distributed storage system for structured data. *OSDI* 2006.
3. B. Bloom. Space/time trade-offs in hash coding with allowable errors. *Communications of the ACM* 13(7), 422–426, 1970.
4. A. Kirsch, M. Mitzenmacher. Less hashing, same performance: building a better bloom filter. *ESA* 2006.
