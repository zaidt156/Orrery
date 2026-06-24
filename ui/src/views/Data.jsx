import { useEffect, useRef, useState } from "react";
import {
  listDataConnections, addDataConnection, deleteDataConnection, listTables, browseTable,
  listCollections, createCollection, deleteCollection, uploadDocuments,
} from "../lib/api.js";

const dot = (ok) => ({
  width: "7px", height: "7px", borderRadius: "50%",
  background: ok ? "var(--green)" : "var(--faint)",
  ...(ok ? { boxShadow: "0 0 6px var(--green)" } : {}),
});

const selStyle = {
  background: "var(--bg0)", border: "1px solid var(--line)", borderRadius: "8px",
  padding: "6px 10px", fontSize: "12px", color: "var(--text)", fontFamily: "var(--font-mono)",
};

function readFile(file, kind) {
  return new Promise((resolve) => {
    const r = new FileReader();
    r.onload = () => resolve({ name: file.name, mime: file.type, kind, content: r.result });
    if (kind === "pdf") r.readAsDataURL(file);
    else r.readAsText(file);
  });
}

export default function Data() {
  const [conns, setConns] = useState([]);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [activeConn, setActiveConn] = useState(null);
  const [tables, setTables] = useState([]);
  const [active, setActive] = useState(null);
  const [grid, setGrid] = useState(null);

  const [cols, setCols] = useState([]);
  const [colAdding, setColAdding] = useState(false);
  const [colName, setColName] = useState("");
  const [colBusy, setColBusy] = useState(false);
  const uploadTarget = useRef(null);
  const fileRef = useRef(null);

  const loadConns = () =>
    listDataConnections().then((d) => setConns(d.connections)).catch((e) => setErr(String(e.message || e)));
  const loadCols = () =>
    listCollections().then((d) => setCols(d.collections)).catch((e) => setErr(String(e.message || e)));
  useEffect(() => { loadConns(); loadCols(); }, []);

  async function add() {
    if (!url.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await addDataConnection(name.trim(), url.trim());
      setName(""); setUrl(""); setAdding(false); loadConns();
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function openConn(c) {
    setActiveConn(c); setActive(null); setGrid(null); setTables([]); setErr(null);
    try { setTables((await listTables(c.id)).tables); } catch (e) { setErr(String(e.message || e)); }
  }

  async function openTable(t) {
    setActive(t); setGrid(null); setErr(null);
    try { setGrid(await browseTable(activeConn.id, t.schema, t.table, 100)); } catch (e) { setErr(String(e.message || e)); }
  }

  async function remove(c, e) {
    e.stopPropagation();
    await deleteDataConnection(c.id);
    if (activeConn && activeConn.id === c.id) { setActiveConn(null); setTables([]); setActive(null); setGrid(null); }
    loadConns();
  }

  async function addCol() {
    setColBusy(true);
    setErr(null);
    try {
      await createCollection(colName.trim());
      setColName(""); setColAdding(false); loadCols();
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setColBusy(false);
    }
  }

  function pickUpload(id) {
    uploadTarget.current = id;
    fileRef.current?.click();
  }

  async function handleColFiles(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    const id = uploadTarget.current;
    if (!id || !files.length) return;
    setErr(null);
    const ready = [];
    for (const f of files) {
      const isPdf = f.type === "application/pdf" || /\.pdf$/i.test(f.name);
      const isText = f.type.startsWith("text/") || /\.(md|csv|json|txt|py|js|ts|jsx|tsx|html|css|ya?ml|log|sql)$/i.test(f.name);
      if (!isPdf && !isText) { setErr(`Unsupported file (skipped ${f.name}). Use text or PDF.`); continue; }
      if (f.size > 12 * 1024 * 1024) { setErr(`${f.name} is too large (max 12 MB).`); continue; }
      ready.push(await readFile(f, isPdf ? "pdf" : "text"));
    }
    if (!ready.length) return;
    try {
      await uploadDocuments(id, ready);
      loadCols();
    } catch (e2) {
      setErr(String(e2.message || e2));
    }
  }

  async function removeCol(c, e) {
    e.stopPropagation();
    await deleteCollection(c.id);
    loadCols();
  }

  return (
    <section className="view">
      <div className="data-wrap">
        <span className="view-title">Data</span>

        <div className="section-label">Database connections · read-only</div>
        {err && <div className="chat-banner">{err}</div>}
        <div className="card-row">
          {conns.map((c) => (
            <div
              key={c.id}
              className="card"
              style={{ cursor: "pointer", ...(activeConn && activeConn.id === c.id ? { borderColor: "var(--amber)" } : {}) }}
              onClick={() => openConn(c)}
            >
              <h4><span className="sdot" style={dot(c.reachable)} />{c.name}</h4>
              <div className="meta">{c.display}<br />{c.reachable ? "connected · read-only" : "unreachable"}</div>
              <div className="foot">
                <span className="tag">read-only</span>
                <button className="btn ghost" style={{ padding: "4px 10px", fontSize: "11px" }} onClick={(e) => remove(c, e)}>Remove</button>
              </div>
            </div>
          ))}
          {!adding && <div className="card add" onClick={() => setAdding(true)}>+ Add connection</div>}
          {adding && (
            <div className="card">
              <h4>New connection</h4>
              <input className="search" style={{ width: "100%", marginTop: "8px" }} placeholder="Name (e.g. analytics)" value={name} onChange={(e) => setName(e.target.value)} />
              <input className="search" style={{ width: "100%", marginTop: "6px" }} placeholder="postgresql://user:password@host:5432/db" value={url} onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
              <div className="foot">
                <button className="btn primary" disabled={busy} onClick={add}>{busy ? "Testing…" : "Add"}</button>
                <button className="btn ghost" onClick={() => { setAdding(false); setErr(null); }}>Cancel</button>
              </div>
            </div>
          )}
        </div>

        <div className="section-label">Document collections · RAG (local embeddings)</div>
        <input ref={fileRef} type="file" multiple hidden accept="application/pdf,.pdf,text/*,.md,.csv,.json,.txt,.py,.js,.ts,.jsx,.tsx,.html,.css,.yml,.yaml,.log,.sql" onChange={handleColFiles} />
        <div className="card-row">
          {cols.map((c) => (
            <div key={c.id} className="card">
              <h4>{c.name}</h4>
              <div className="meta">{c.chunks} chunks · {c.embed_model}<br />on-device embeddings</div>
              <div className="foot">
                <button className="btn ghost" style={{ padding: "4px 10px", fontSize: "11px" }} onClick={() => pickUpload(c.id)}>+ Add files</button>
                <button className="btn ghost" style={{ padding: "4px 10px", fontSize: "11px" }} onClick={(e) => removeCol(c, e)}>Remove</button>
              </div>
            </div>
          ))}
          {!colAdding && <div className="card add" onClick={() => setColAdding(true)}>+ New collection</div>}
          {colAdding && (
            <div className="card">
              <h4>New collection</h4>
              <input className="search" style={{ width: "100%", marginTop: "8px" }} placeholder="Name (e.g. product docs)" value={colName} onChange={(e) => setColName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") addCol(); }} />
              <div className="foot">
                <button className="btn primary" disabled={colBusy} onClick={addCol}>{colBusy ? "Creating…" : "Create"}</button>
                <button className="btn ghost" onClick={() => { setColAdding(false); setErr(null); }}>Cancel</button>
              </div>
            </div>
          )}
        </div>
        <div className="meta" style={{ fontFamily: "var(--font-mono)", color: "var(--faint)", marginTop: "6px" }}>
          Drop text or PDF files into a collection, then toggle “Use my data” in Chat to answer from them.
        </div>

        <div className="section-label">Table browser{activeConn ? ` · ${activeConn.name}` : ""}</div>
        {!activeConn && (
          <div className="meta" style={{ fontFamily: "var(--font-mono)", color: "var(--faint)" }}>
            Pick a connection above to browse its tables (read-only).
          </div>
        )}
        {activeConn && (
          <div className="table-shell">
            <div className="table-bar">
              <span className="pill">{tables.length} tables</span>
              <select
                style={selStyle}
                value={active ? `${active.schema}.${active.table}` : ""}
                onChange={(e) => {
                  const t = tables.find((x) => `${x.schema}.${x.table}` === e.target.value);
                  if (t) openTable(t);
                }}
              >
                <option value="">choose a table…</option>
                {tables.map((t) => (
                  <option key={`${t.schema}.${t.table}`} value={`${t.schema}.${t.table}`}>
                    {t.schema}.{t.table}
                  </option>
                ))}
              </select>
              <span className="pill">read-only query</span>
            </div>
            {grid && (
              <>
                <div style={{ overflowX: "auto" }}>
                  <table className="dtable">
                    <tbody>
                      <tr>{grid.columns.map((c) => <th key={c}>{c}</th>)}</tr>
                      {grid.rows.map((row, i) => (
                        <tr key={i}>{row.map((cell, j) => <td key={j}>{cell === null ? "∅" : String(cell)}</td>)}</tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="table-foot">{grid.rows.length} rows · capped &amp; time-limited · read-only</div>
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
