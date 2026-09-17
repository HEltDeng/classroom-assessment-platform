import { useEffect, useState, useRef } from 'react'
import { getToken } from './api'

const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
async function authenticated(path: string, init: RequestInit = {}) {
  const response = await fetch(base + path, { ...init, headers: { Authorization: `Bearer ${getToken()}`, ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers } })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败 (${response.status})`)
  }
  return response
}

export function SheetDownload({ path, label = '下载 A5 答题卡' }: { path: string; label?: string }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function download() {
    setBusy(true); setError('')
    try {
      const response = await authenticated(path)
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a'); link.href = url; link.download = 'answer-sheets-a5.pdf'; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <span><button type="button" className="button button-secondary" disabled={busy} onClick={download}>{busy ? '正在生成…' : label}</button>{error && <span role="alert">{error}</span>}</span>
}

export function StudentCardButton({ studentId, name }: { studentId: string; name: string }) {
  const [open, setOpen] = useState(false)
  const [card, setCard] = useState<{ qr_svg: string; student_code: string } | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!open) return
    let cancelled = false
    authenticated(`/students/${studentId}/answer-card`).then(r => r.json()).then(data => { if (!cancelled) setCard(data) }).catch(e => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [open, studentId])
  return <><button type="button" className="text-button" onClick={() => setOpen(true)} aria-label={`查看${name}的二维码与答题卡`}>{name}</button>{open && <div className="card-backdrop" onClick={() => setOpen(false)}><section className="answer-card-modal panel" role="dialog" aria-modal="true" aria-label={`${name}的答题卡`} onClick={e => e.stopPropagation()}><button autoFocus className="icon-button card-close" aria-label="关闭答题卡" onClick={() => setOpen(false)}>×</button><h2>{name}</h2>{error && <p role="alert">{error}</p>}{card ? <><strong>{card.student_code}</strong><img className="student-qr" alt="学生页面二维码" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(card.qr_svg)}`} /><p>A5 双面：40 道选择题 + 10 道文字题。</p><p className="muted-copy">重复下载保持身份不变。双面打印请选择实际大小、长边翻页；题量较多时从考试页下载完整卡片。</p><SheetDownload path={`/students/${studentId}/answer-sheet.pdf`} /></> : !error && <p>正在生成二维码…</p>}</section></div>}</>
}

interface Scan {
  server_scan_id: string; student_name: string | null; student_code: string | null; status: string; page_type: string; failure_reason: string | null
  recognition: { mapped_answers: Array<{ question_no: number; value: string; confidence: number; status: string }> } | null
}

export function ScanReviewPanel({ sessionId, archived, onSaved }: { sessionId: string; archived: boolean; onSaved: () => void }) {
  const [scans, setScans] = useState<Scan[]>([])
  const [selected, setSelected] = useState<Scan | null>(null)
  const [answers, setAnswers] = useState<Record<number, string>>({})
  const [image, setImage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const lastSignature = useRef('')
  const savedCallback = useRef(onSaved)
  savedCallback.current = onSaved
  async function refresh() {
    const data: Scan[] = await (await authenticated(`/sessions/${sessionId}/scans`)).json()
    setScans(data)
    const signature = data.map(s => s.server_scan_id+s.status).join(',')
    if (lastSignature.current !== signature) { lastSignature.current = signature; savedCallback.current() }
  }
  useEffect(() => { const update = () => refresh().catch(e => setError(e.message)); void update(); const timer = setInterval(update, 5000); return () => clearInterval(timer) }, [sessionId])
  useEffect(() => {
    if (!selected) return
    let active = true; let objectUrl = ''
    setImage(''); setAnswers(Object.fromEntries((selected.recognition?.mapped_answers || []).map(a => [a.question_no, a.value])))
    authenticated(`/scans/${selected.server_scan_id}/image`).then(r => r.blob()).then(blob => { objectUrl = URL.createObjectURL(blob); if (active) setImage(objectUrl); else URL.revokeObjectURL(objectUrl) }).catch(e => { if (active) setError(e.message) })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [selected])
  async function save() {
    if (!selected) return
    setBusy(true); setError('')
    try {
      await authenticated(`/scans/${selected.server_scan_id}/review`, { method: 'POST', body: JSON.stringify({ answers: Object.entries(answers).map(([n, value]) => ({ question_no: Number(n), value })) }) })
      setSelected(null); await refresh(); onSaved()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const labels: Record<string, string> = { PROCESSING: '处理中', REVIEW_REQUIRED: '待复核', SUCCESS: '已完成', FAILED: '失败' }
  return <section className="panel"><div className="panel-heading"><h2>扫描与复核</h2><SheetDownload path={`/sessions/${sessionId}/answer-sheets.pdf`} label="批量下载本场答题卡" /></div><p className="muted-copy">考试结束后仍可扫描和核验。文字题保留识别原文，确认后按正确答案核对；归档后停止录入。</p>{error && <p role="alert">{error}</p>}{!scans.length && <p>暂无扫描记录。下载答题卡后，在安卓端选择本场考试开始扫描。</p>}<div className="scan-review-list">{scans.map(scan => <div key={scan.server_scan_id}><span>{scan.student_name || '身份待确认'} · {scan.student_code} · {scan.page_type.startsWith('A5-OCR') ? '文字面' : '选择面'} · {labels[scan.status]}</span><button className="button button-quiet" onClick={() => setSelected(scan)}>查看{scan.status === 'REVIEW_REQUIRED' ? ' / 核验' : ''}</button>{!archived && ['FAILED', 'REVIEW_REQUIRED'].includes(scan.status) && <button className="button button-quiet" onClick={() => authenticated(`/scans/${scan.server_scan_id}/retry`, { method: 'POST' }).then(refresh).catch(e => setError(e.message))}>重新识别</button>}{scan.failure_reason && <small>{scan.failure_reason}</small>}</div>)}</div>{selected && <div className="scan-review-editor"><div>{image && <img src={image} alt="原始答题卡照片" />}</div><div><h3>{selected.student_name} · 原图核验</h3>{(selected.recognition?.mapped_answers || []).map(a => <label key={a.question_no}>第 {a.question_no} 题 · 原文：{a.value || '空白'}<input value={answers[a.question_no] ?? ''} disabled={archived || selected.status !== 'REVIEW_REQUIRED'} onChange={e => setAnswers(old => ({ ...old, [a.question_no]: e.target.value }))} maxLength={2000} /></label>)}<div className="button-row">{!archived && selected.status === 'REVIEW_REQUIRED' && selected.recognition && <button className="button button-primary" onClick={save} disabled={busy}>确认核验并计分</button>}<button className="button button-quiet" onClick={() => setSelected(null)}>关闭</button></div></div></div>}</section>
}
