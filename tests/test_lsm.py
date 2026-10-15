import os, random, shutil, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lsm import LSMTree, BloomFilter  # noqa


class TestLSM(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_model_based_random_ops(self):
        """Compare against a dict across puts, overwrites, deletes, flushes and compactions."""
        rng = random.Random(0)
        db, model = LSMTree(self.dir, memtable_bytes=4096, compaction_trigger=3), {}
        for i in range(20000):
            k = f"k{rng.randrange(1500):05d}".encode()
            r = rng.random()
            if r < 0.6:
                v = os.urandom(rng.randrange(1, 40)); db.put(k, v); model[k] = v
            elif r < 0.8:
                db.delete(k); model.pop(k, None)
            else:
                self.assertEqual(db.get(k), model.get(k))
        for k in {f"k{i:05d}".encode() for i in range(1500)}:
            self.assertEqual(db.get(k), model.get(k))
        self.assertEqual(db.scan(b"k00100", b"k00200"), sorted((k, v) for k, v in model.items() if b"k00100" <= k < b"k00200"))
        self.assertGreater(db.stats["compactions"], 0)
        db.close()

    def test_reopen_after_clean_close(self):
        db = LSMTree(self.dir, memtable_bytes=2048)
        for i in range(3000):
            db.put(f"{i}".encode(), f"v{i}".encode())
        db.delete(b"7")
        db.close()
        db = LSMTree(self.dir, memtable_bytes=2048)
        self.assertEqual(db.get(b"2999"), b"v2999")
        self.assertIsNone(db.get(b"7"))
        db.close()

    def test_crash_with_torn_wal_tail(self):
        """Simulate a crash mid-write: truncate the WAL at random byte positions; every complete record must survive."""
        rng = random.Random(1)
        for trial in range(20):
            d = tempfile.mkdtemp()
            db = LSMTree(d, memtable_bytes=1 << 30)            # never flush: everything lives in the WAL
            n = rng.randrange(50, 300)
            for i in range(n):
                db.put(f"key{i}".encode(), f"value{i}".encode())
            db.wal.flush()
            wal = db._wal_path(); size = os.path.getsize(wal)
            cut = rng.randrange(0, size)
            db.wal.close()
            with open(wal, "r+b") as f:
                f.truncate(cut)
            db2 = LSMTree(d, memtable_bytes=1 << 30)
            m = db2.stats["recovered_records"]
            for i in range(m):
                self.assertEqual(db2.get(f"key{i}".encode()), f"value{i}".encode())
            for i in range(m, n):
                self.assertIsNone(db2.get(f"key{i}".encode()))
            db2.put(b"after", b"crash"); db2.close()
            db3 = LSMTree(d, memtable_bytes=1 << 30)
            self.assertEqual(db3.get(b"after"), b"crash")    # torn tail was truncated, new appends are readable
            db3.close(); shutil.rmtree(d)

    def test_bloom_false_positive_rate(self):
        b = BloomFilter(10000, 0.01)
        for i in range(10000):
            b.add(f"in{i}".encode())
        self.assertTrue(all(f"in{i}".encode() in b for i in range(10000)))
        fp = sum(f"out{i}".encode() in b for i in range(20000)) / 20000
        self.assertLess(fp, 0.02)


if __name__ == "__main__":
    unittest.main()
