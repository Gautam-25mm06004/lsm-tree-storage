# Results

## Bloom filter false-positive rate (20,000 keys, 50,000 negative probes)

| bits_per_key | hashes | measured_fp_% | theory_fp_% |
|---|---|---|---|
| 4 | 3 | 14.824 | 14.689 |
| 6 | 4 | 5.51 | 5.606 |
| 8 | 6 | 2.088 | 2.158 |
| 10 | 7 | 0.826 | 0.819 |
| 12 | 8 | 0.29 | 0.314 |
| 16 | 11 | 0.044 | 0.046 |

## Compaction trade-off (60,000 random writes of 100-byte values, 64 KB memtable; 5,000 lookups)

| compaction_trigger | bloom | sstables | write_amplification | write_kops_per_s | block_reads_per_get | block_reads_per_missing_get | get_latency_us |
|---|---|---|---|---|---|---|---|
| 2 | True | 1 | 50.81 | 5.1 | 0.4 | 0.012 | 12.3 |
| 2 | False | 1 | 50.81 | 4.5 | 1.0 | 1.0 | 11.5 |
| 4 | True | 1 | 18.69 | 13.8 | 0.4 | 0.012 | 8.1 |
| 4 | False | 1 | 18.69 | 11.4 | 1.0 | 1.0 | 11.3 |
| 8 | True | 5 | 9.01 | 21.3 | 0.45 | 0.059 | 22.6 |
| 8 | False | 5 | 9.01 | 25.6 | 4.97 | 4.991 | 49.1 |
| never | True | 103 | 2.2 | 110.1 | 1.24 | 1.07 | 164.5 |
| never | False | 103 | 2.2 | 116.3 | 81.13 | 102.824 | 918.5 |

## Durability cost

| fsync_every_write | writes_per_s | mean_latency_us |
|---|---|---|
| False | 480808 | 2.1 |
| True | 7070 | 141.4 |

## Recovery (WAL replay)

| wal_records | wal_MB | recovery_s | records_per_s |
|---|---|---|---|
| 10000 | 0.7 | 0.013 | 777999 |
| 50000 | 3.6 | 0.058 | 856174 |
| 200000 | 14.6 | 0.316 | 633694 |
