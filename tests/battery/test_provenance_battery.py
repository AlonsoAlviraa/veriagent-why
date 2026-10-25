"""Data / provenance guards: frozen split hashes and disjointness, no test-set leakage, dirty-tree abort."""
import glob, hashlib, json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPLITS = sorted(glob.glob(str(ROOT / "docs/v9/gen/split_gen_*.json")) + glob.glob(str(ROOT / "docs/v10/hard/split_hard_*.json")))
MAIN = [s for s in SPLITS if not s.endswith("_pilot.json")]


def j(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


@pytest.mark.parametrize("sp", SPLITS, ids=lambda p: Path(p).stem)
def test_split_dataset_hash_matches_frozen_file(sp):
    d = j(sp); ds = Path(sp).parent / f"tatqa_dataset_{d['tatqa_split']}.json"
    assert hashlib.sha256(ds.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == d["dataset_sha256"]


@pytest.mark.parametrize("sp", SPLITS, ids=lambda p: Path(p).stem)
def test_split_ids_exist_and_unique(sp):
    d = j(sp); ds = j(Path(sp).parent / f"tatqa_dataset_{d['tatqa_split']}.json")
    uids = [q["uid"] for doc in ds for q in doc["questions"]]
    assert len(uids) == len(set(uids))
    assert len(d["ids"]) == len(set(d["ids"])) and set(d["ids"]) <= set(uids)


@pytest.mark.parametrize("sp", MAIN, ids=lambda p: Path(p).stem)
def test_cal_test_pilot_disjoint_and_grouped_by_document(sp):
    d = j(sp); pilot = j(sp.replace(".json", "_pilot.json"))["ids"]
    cal, test = set(d["cal_ids"]), set(d["test_ids"])
    assert not cal & test and cal | test == set(d["ids"]) and not set(pilot) & set(d["ids"])
    ds = j(Path(sp).parent / f"tatqa_dataset_{d['tatqa_split']}.json")
    doc = {q["uid"]: x["table"]["uid"] for x in ds for q in x["questions"]}
    assert not {doc[i] for i in cal} & {doc[i] for i in test}, "a document is in both cal and test"
    assert not {doc[i] for i in pilot} & {doc[i] for i in d["ids"]}, "pilot shares a document with the main set"


ALL_SETS = sorted({j(s)["tatqa_split"]: s for s in MAIN}.items())


@pytest.mark.parametrize("a,b", [(x, y) for i, x in enumerate(ALL_SETS) for y in ALL_SETS[i + 1:]], ids=lambda t: t[0])
def test_sets_pairwise_disjoint(a, b):
    assert not set(j(a[1])["ids"]) & set(j(b[1])["ids"])


def test_holdout_and_test500_disjoint_and_hashed():
    h = j(ROOT / "bench/splits/holdout_v1.json"); t = j(ROOT / "bench/splits/tatqa_test500_v1.json")
    assert not set(h["ids"]) & set(t["ids"])
    for d in (h, t):
        assert hashlib.sha256("\n".join(d["ids"]).encode()).hexdigest() == d["ids_sha256"]
    assert len(t["ids"]) == 500 and len(h["ids"]) == 100


TQ = ROOT / "data/bench/tatqa"
need = pytest.mark.skipif(not (TQ / "tatqa_dataset_test_gold.json").exists(), reason="TAT-QA not downloaded (make data)")


@need
def test_test_gold_never_in_train_or_dev():
    u = lambda f: {q["uid"] for d in j(TQ / f) for q in d["questions"]}
    tg = u("tatqa_dataset_test_gold.json")
    assert not tg & u("tatqa_dataset_train.json") and not tg & u("tatqa_dataset_dev.json")
    t = j(ROOT / "bench/splits/tatqa_test500_v1.json")
    assert set(t["ids"]) <= tg


@need
def test_test500_ids_not_in_any_test_fixture_or_doc():
    t = j(ROOT / "bench/splits/tatqa_test500_v1.json")["ids"][:500]
    blob = "".join(p.read_text(errors="ignore") for p in (ROOT / "tests").rglob("*.py") if "battery" not in str(p))
    assert not [i for i in t if i in blob]


def test_dirty_tree_aborts_real_runs(monkeypatch):
    from bench import run
    monkeypatch.setattr(run, "git_state", lambda: {"code_rev": "x", "code_rev_full": "x", "dirty": True, "dirty_files": ["a.py"]})
    with pytest.raises(SystemExit) as e:
        run.main(["--bench", "tatqa", "--systems", "rag", "--limit", "1"])
    assert "dirty" in str(e.value)
