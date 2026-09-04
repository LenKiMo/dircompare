/* dircompare 比对引擎（纯 JS，浏览器/Node 通用；依赖 WebCrypto crypto.subtle）
 * 输入条目：{ name: 相对路径, size: 字节数, read: async () => ArrayBuffer }
 * 逻辑与 Python 版 dircompare.py 一一对应（按大小分层 -> 哈希 -> 分组配对 确定/推测）
 */
"use strict";

function natKey(rel) {
    let s = String(rel).replace(/\\/g, "/").split("/").pop();
    let dot = s.lastIndexOf(".");
    if (dot > 0) s = s.slice(0, dot);
    let m = s.match(/^(\d+)/);
    return m ? [parseInt(m[1], 10), s.slice(m[0].length)] : [1e12, s];
}
function baseName(rel) {
    return String(rel).replace(/\\/g, "/").split("/").pop();
}
function humanSize(n) {
    if (n < 1024) return n + " B";
    const u = ["KB", "MB", "GB", "TB"];
    let v = n;
    for (let i = 0; i < u.length; i++) {
        v /= 1024;
        if (v < 1024 || i === u.length - 1) return v.toFixed(v >= 10 ? 1 : 2) + " " + u[i];
    }
}
function bufToHex(buf) {
    const b = new Uint8Array(buf);
    let s = "";
    for (let i = 0; i < b.length; i++) s += (b[i] < 16 ? "0" : "") + b[i].toString(16);
    return s;
}
async function digestHex(buf, algo) {
    return bufToHex(await crypto.subtle.digest(algo, buf));
}

/* entries: {name,size,read}[]  两侧各自一个数组
 * opts: { algo:'SHA-256'|'SHA-1', onProgress:(done,total,label)=>void, maxReadBytes?:警告阈值 }
 * 返回 report，结构与 Python 版对应：
 *   stats{nA,nB,zA,zB,bytesA,bytesB,nMatchA,nMatchB,nPairs,nCertain,nOnlyA,nOnlyB,nND,nErr,ms}
 *   pairs:[{a,b,certain,sameName,extra:'A'|'B'|null}]  a/b 为条目或 null
 *   onlyA, onlyB: 条目数组；namesDiff:[{a,b}]；errs:[{name,msg}]
 */
async function runCompare(entriesA, entriesB, opts) {
    opts = opts || {};
    const algo = opts.algo || "SHA-256";
    const t0 = Date.now();
    const stat = (arr) => arr.reduce((s, e) => { s.n++; s.bytes += e.size || 0; if (!e.size) s.z++; return s; }, { n: 0, bytes: 0, z: 0 });
    const effA = entriesA.filter(e => e.size > 0), effB = entriesB.filter(e => e.size > 0); // 0 字节仅计数，不参与匹配（与 Python 版一致）

    const bySize = new Map();
    for (const e of effA) { e.side = "A"; if (!bySize.has(e.size)) bySize.set(e.size, []); bySize.get(e.size).push(e); }
    for (const e of effB) { e.side = "B"; if (!bySize.has(e.size)) bySize.set(e.size, []); bySize.get(e.size).push(e); }

    const cand = [];
    for (const [size, arr] of bySize) {
        if (size > 0 && new Set(arr.map(x => x.side)).size === 2) cand.push(...arr);
    }
    const errs = [];
    let done = 0;
    const total = cand.length;
    for (const e of cand) {
        try {
            const buf = await e.read();
            if (buf.byteLength !== e.size) throw new Error("读取大小不一致 " + buf.byteLength + "≠" + e.size);
            e.sha = await digestHex(buf, algo);
        } catch (ex) {
            e.err = String(ex && ex.message || ex);
            errs.push({ name: e.name, msg: e.err });
        }
        done++;
        if (opts.onProgress) opts.onProgress(done, total, e.name);
    }

    const groups = new Map();
    for (const e of cand) {
        if (!e.sha) continue;
        const k = e.size + "|" + e.sha;
        if (!groups.has(k)) groups.set(k, { A: [], B: [] });
        groups.get(k)[e.side].push(e);
    }
    const matchedA = new Set(), matchedB = new Set();
    const pairs = [];
    for (const [k, g] of groups) {
        if (!g.A.length || !g.B.length) continue;
        g.A.sort((x, y) => natKey(x.name) < natKey(y.name) ? -1 : 1);
        g.B.sort((x, y) => natKey(x.name) < natKey(y.name) ? -1 : 1);
        const ua = new Set(g.A.map(x => x.size)).size === g.A.length;
        const ub = new Set(g.B.map(x => x.size)).size === g.B.length;
        if (ua && ub) {
            const bMap = new Map(g.B.map(x => [x.size, x]));
            for (const a of g.A) pairs.push({ a, b: bMap.get(a.size), certain: true, sameName: baseName(a.name) === baseName(bMap.get(a.size).name), extra: null });
        } else {
            const n = Math.min(g.A.length, g.B.length);
            for (let i = 0; i < n; i++) pairs.push({ a: g.A[i], b: g.B[i], certain: false, sameName: baseName(g.A[i].name) === baseName(g.B[i].name), extra: null });
            for (let i = n; i < g.A.length; i++) pairs.push({ a: g.A[i], b: null, certain: false, sameName: false, extra: "A" });
            for (let i = n; i < g.B.length; i++) pairs.push({ a: null, b: g.B[i], certain: false, sameName: false, extra: "B" });
        }
        g.A.forEach(x => matchedA.add(x));
        g.B.forEach(x => matchedB.add(x));
    }
    const onlyA = effA.filter(e => !matchedA.has(e));
    const onlyB = effB.filter(e => !matchedB.has(e));

    const nameMapA = new Map(), nameMapB = new Map();
    for (const e of effA) { if (!nameMapA.has(baseName(e.name))) nameMapA.set(baseName(e.name), []); nameMapA.get(baseName(e.name)).push(e); }
    for (const e of effB) { if (!nameMapB.has(baseName(e.name))) nameMapB.set(baseName(e.name), []); nameMapB.get(baseName(e.name)).push(e); }
    const namesDiff = [];
    for (const nm of nameMapA.keys()) {
        if (!nameMapB.has(nm)) continue;
        for (const a of nameMapA.get(nm)) for (const b of nameMapB.get(nm))
            if (a.size !== b.size || (a.sha || "") !== (b.sha || "")) namesDiff.push({ a, b });
    }
    const mbA = [...matchedA].reduce((s, e) => s + e.size, 0);
    const mbB = [...matchedB].reduce((s, e) => s + e.size, 0);
    const real = pairs.filter(p => p.a && p.b);
    const sa = stat(effA), sb = stat(effB);
    const stats = {
        nA: sa.n, nB: sb.n, zA: entriesA.length - effA.length, zB: entriesB.length - effB.length, bytesA: sa.bytes, bytesB: sb.bytes,
        nMatchA: matchedA.size, nMatchB: matchedB.size, nPairs: real.length,
        nCertain: real.filter(p => p.certain).length,
        mbA, mbB, nOnlyA: onlyA.length, nOnlyB: onlyB.length,
        nND: namesDiff.length, nErr: errs.length, ms: Date.now() - t0,
    };
    return { stats, pairs, onlyA, onlyB, namesDiff, errs };
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = { runCompare, natKey, baseName, humanSize };
}
