"""ZetarisJdbcBackend, loader and check script against a fake JayDeBeApi connection (no Java, no live
Zetaris). The fake executes the rendered Lightning SQL on the local DuckDB snapshot, so the full pipeline
is exercised through the JDBC code path (rendering, literals, prefixing, value conversion)."""
import importlib, re, sys, types
from pathlib import Path
import duckdb, pytest
from app.adapters import zetaris as z

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class FakeCursor:
    def __init__(self, con, log):
        self.con, self.log, self.description, self._rows = con, log, None, []

    def execute(self, sql):
        assert ";" not in sql.strip().rstrip(";"), "one statement per call"
        self.log.append(sql)
        if sql.upper().startswith(("SHOW", "CREATE", "REGISTER", "DROP")):
            self.description, self._rows = ([("name",)], [("veriagent_pg",)]) if sql.startswith("SHOW") else (None, [])
            return
        duck = re.sub(r"\bAS STRING\b", "AS VARCHAR", sql).replace("veriagent.", "").replace("\\'", "''")
        cur = self.con.execute(duck)
        self.description = [(f"t.{d[0]}".upper(),) for d in cur.description]  # drivers may qualify/uppercase
        self._rows = cur.fetchall()

    def fetchall(self):
        if self.description is None:
            raise RuntimeError("no result set")
        return self._rows

    def close(self):
        pass


class FakeConn:
    def __init__(self):
        self.con, self.log = duckdb.connect(str(ROOT / "data" / "snapshot.duckdb"), read_only=True), []

    def cursor(self):
        return FakeCursor(self.con, self.log)


def test_render_literals_prefix_and_dialect():
    sql = z.render("SELECT CAST(ship_date AS VARCHAR) d FROM v_logistics l JOIN v_orders o USING(order_id) "
                   "WHERE region = ? AND n > ? AND ok = ?;", ["O'Brien", 3, True], "veriagent.")
    assert sql == ("SELECT CAST(ship_date AS STRING) d FROM veriagent.v_logistics l JOIN veriagent.v_orders o "
                   "USING(order_id) WHERE region = 'O\\'Brien' AND n > 3 AND ok = TRUE")
    assert z.render("SELECT * FROM x.v_orders", [], "veriagent.") == "SELECT * FROM x.v_orders"
    with pytest.raises(ValueError):
        z.render("SELECT ?", [], "")


def test_connect_reads_env_and_rejects_jar_in_repo(monkeypatch, tmp_path):
    calls = {}
    fake = types.SimpleNamespace(connect=lambda cls, url, creds, jar: calls.update(cls=cls, url=url, creds=creds, jar=jar) or "C")
    monkeypatch.setitem(sys.modules, "jaydebeapi", fake)
    jar = tmp_path / "driver.jar"; jar.write_bytes(b"x")
    monkeypatch.setenv("ZETARIS_JDBC_JAR", str(jar)); monkeypatch.setenv("ZETARIS_USER", "u")
    monkeypatch.setenv("ZETARIS_PASSWORD", "test-not-a-secret"); monkeypatch.delenv("ZETARIS_JDBC_URL", raising=False)
    assert z.jdbc_connect() == "C"
    assert calls == {"cls": "com.zetaris.lightning.jdbc.LightningDriver", "url": "jdbc:zetaris:lightning@localhost:10000",
                     "creds": ["u", "test-not-a-secret"], "jar": str(jar)}
    inside = ROOT / "data" / "driver.jar"
    monkeypatch.setenv("ZETARIS_JDBC_JAR", str(inside))
    inside.write_bytes(b"x")
    try:
        with pytest.raises(RuntimeError, match="outside the repo"):
            z.jdbc_connect()
    finally:
        inside.unlink()
    monkeypatch.delenv("ZETARIS_PASSWORD")
    with pytest.raises(RuntimeError, match="ZETARIS_PASSWORD"):
        z.jdbc_connect()


def test_backend_default_is_sample(monkeypatch):
    monkeypatch.delenv("ZETARIS_BACKEND", raising=False)
    assert z.get_backend().name == "sample-duckdb"


def test_pipeline_through_jdbc_backend(monkeypatch):
    import json
    from app import pipeline
    conn = FakeConn()
    monkeypatch.setattr(pipeline, "get_backend", lambda ds=None: z.ZetarisJdbcBackend(conn=conn))
    inp = json.loads((ROOT / "input_examples" / "example_1.json").read_text())["input"]
    r = pipeline.run(inp, "test-jdbc")
    assert r["status"] == "success"
    assert r["output"]["result"]["analysis"]["top_cause_label"] == "carrier_sla_breach"
    assert conn.log and all("veriagent.v_" in s for s in conn.log if " v_" in s or "veriagent." in s)


def test_check_script_counts_match(capsys):
    chk = importlib.import_module("zetaris_check")
    assert chk.main(conn=FakeConn()) == 0
    assert "ALL OK" in capsys.readouterr().out


def test_loader_dry_run_touches_nothing(capsys):
    load = importlib.import_module("zetaris_load")
    assert load.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "CREATE DATASOURCE veriagent_pg" in out and "redacted" in out
    assert "CREATE LIGHTNING REST TABLE v_promotions_raw" in out
    assert "SCHEMASTORE VIEW v_tickets WITH CONTAINER veriagent" in out
