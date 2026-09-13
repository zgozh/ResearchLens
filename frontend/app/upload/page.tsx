'use client';

import { useCallback, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { ArrowLeft, FileUp, FileText, Loader2, CheckCircle2, AlertTriangle, Sparkles, Globe } from 'lucide-react';
import { api } from '@/lib/api';
import { workspaceQuery } from '@/lib/paperProgress';
import { Logo } from '@/components/Logo';
import { Btn, GlassCard, Kicker } from '@/components/ui';
import { cn } from '@/lib/cn';

const EXAMPLE_PAPERS = [
  {
    label: 'Attention Is All You Need',
    url: 'https://arxiv.org/pdf/1706.03762',
    note: 'arXiv · Transformer',
  },
  {
    label: 'BERT',
    url: 'https://arxiv.org/pdf/1810.04805',
    note: 'arXiv · NLP',
  },
  {
    label: 'ResNet',
    url: 'https://arxiv.org/pdf/1512.03385',
    note: 'arXiv · 视觉',
  },
  {
    label: 'LoRA',
    url: 'https://arxiv.org/pdf/2106.09685',
    note: 'arXiv · 微调',
  },
  {
    label: 'PLOS ONE 示例',
    url: 'https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0171226&type=printable',
    note: 'PLOS · 开放获取',
  },
];

export default function UploadPage() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [urlMode, setUrlMode] = useState(false);
  const [url, setUrl] = useState('');
  const [stage, setStage] = useState<string>('正在处理…');
  const [error, setError] = useState<string>();
  const [ok, setOk] = useState(false);

  // R4-M7：跳转**必须带上 job_id**（旧实现只带 paper_id，于是 `useJobEvents({job_id: 0})`
  // 永不连接 SSE，页面既没有进度也没有阶段细粒度），并且**立即跳转**
  // —— 那 900ms 的 setTimeout 没有任何作用（响应里 job_id 已经有了，
  // 目标页本来就要处理"作业刚开始"的 pending 态）。
  const goToPaper = (paperId: number, jobId?: number) => {
    router.push(`/paper/upload?${workspaceQuery(paperId, jobId)}`);
  };

  const handleFile = useCallback(async (file?: File | null) => {
    if (!file) return;
    setBusy(true); setOk(false); setError(undefined);
    setStage('正在上传论文…');
    try {
      const up = await api.uploadPaper(file);
      // 服务端现在**自己**跑完整 ingest（与"粘贴网址"同一条 canonical 链路，ADR-0066），
      // 因此不再调 /process —— 否则整条 pipeline 会跑两遍（双倍模型开销）。
      setOk(true);
      setStage('已创建任务，正在进入工作台…');
      goToPaper(up.paper_id, up.job_id);
    } catch (e: any) {
      setError(e?.message || '上传失败');
      setStage('');
    } finally {
      setBusy(false);
    }
  }, [router]);

  const handleUrl = useCallback(async () => {
    const u = url.trim();
    if (!u) return;
    setBusy(true); setOk(false); setError(undefined);
    setStage('正在下载真实论文…');
    try {
      const up = await api.paperFromUrl(u);
      setOk(true);
      setStage('已创建任务，正在进入工作台…');
      goToPaper(up.paper_id);
    } catch (e: any) {
      setError(e?.message || '处理失败');
      setStage('');
    } finally {
      setBusy(false);
    }
  }, [router, url]);

  return (
    <main className="grid-bg relative min-h-screen">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-6">
        <div className="flex items-center gap-4">
          <Link href="/" className="flex items-center gap-2 text-slate-400 transition hover:text-white">
            <ArrowLeft className="h-4 w-4" /> 返回
          </Link>
          <Logo />
        </div>
        <Link href="/" className="text-sm font-medium text-indigo-300 hover:text-indigo-200">选论文 →</Link>
      </header>

      <section className="mx-auto max-w-3xl px-6 py-10 text-center">
        <Kicker>放入·真实论文</Kicker>
        <h1 className="mt-3 text-3xl font-semibold text-white">把一篇论文变成可交互的科研成果</h1>
        <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-slate-400">
          支持 <span className="text-indigo-300">粘贴公开论文网址（如 arXiv）</span> 或 上传本机 PDF；
          上传后 ResearchLens 用真实大模型完成解析→结构→断言→证据→讲解→问答→评测。
        </p>

        <div className="mx-auto mt-6 flex max-w-2xl items-center justify-center gap-2">
          <button onClick={() => setUrlMode(true)} className={cn('rounded-xl px-4 py-2 text-sm font-medium transition', urlMode ? 'bg-indigo-500 text-white' : 'bg-white/[0.04] text-slate-300 hover:bg-white/[0.08]')}>
            <Globe className="mr-1.5 inline h-4 w-4" />粘贴网址
          </button>
          <button onClick={() => setUrlMode(false)} className={cn('rounded-xl px-4 py-2 text-sm font-medium transition', !urlMode ? 'bg-indigo-500 text-white' : 'bg-white/[0.04] text-slate-300 hover:bg-white/[0.08]')}>
            <FileUp className="mr-1.5 inline h-4 w-4" />上传 PDF
          </button>
        </div>

        {urlMode ? (
          <div className="mx-auto mt-6 max-w-2xl">
            <form onSubmit={(e) => { e.preventDefault(); handleUrl(); }} className="flex items-center gap-2">
              <input value={url} onChange={(e) => setUrl(e.target.value)}
                placeholder="粘贴论文网址，如 https://arxiv.org/pdf/1512.03385"
                className="flex-1 rounded-xl border border-[var(--line)] bg-white/[0.03] px-4 py-3 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus:border-white/25" />
              <Btn type="submit" variant="primary">下载并处理</Btn>
            </form>
            {/* 示例论文网址：**全部实测可解析**（下载得到真 PDF，不是摘要页/HTML）。
                选这些是因为它们是开放获取的PDF 直链——摘要页贴进来会返回 HTML，
                后端现在会明确拒绝并提示改用直链（ADR-0064）。 */}
            <div className="mt-4 text-left">
              <p className="mb-2 text-[11px] text-slate-500">
                可以直接点下面任意一篇试试（都是开放获取的 PDF 直链，实测可完整解析）：
              </p>
              <div className="flex flex-wrap gap-2">
                {EXAMPLE_PAPERS.map((p) => (
                  <button
                    key={p.url}
                    type="button"
                    onClick={() => setUrl(p.url)}
                    title={p.url}
                    className="group inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] bg-white/[0.03] px-2.5 py-1.5 text-[11px] text-slate-300 transition hover:border-indigo-400/40 hover:bg-indigo-500/10 hover:text-indigo-200"
                  >
                    <FileText className="h-3 w-3 text-slate-500 group-hover:text-indigo-300" />
                    {p.label}
                    <span className="font-mono text-[10px] text-slate-600">{p.note}</span>
                  </button>
                ))}
              </div>
              <p className="mt-2 font-mono text-[10px] text-slate-600">
                点击只会填入输入框，不会自动下载；确认后再按"下载并处理"。
              </p>
            </div>
            <p className="mt-3 text-left font-mono text-[11px] text-slate-600">
              请粘贴论文 <span className="text-slate-400">PDF 直链</span>（如 arXiv 的 /pdf/xxxx）；
              摘要页/HTML 页会被拒收并提示原因。下载后后台完整抽取，进入后可看进度。
            </p>
          </div>
        ) : (
          <div className="mt-8">
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files?.[0]); }}
              onClick={() => inputRef.current?.click()}
              className={cn('group relative mx-auto flex min-h-[260px] max-w-2xl cursor-pointer flex-col items-center justify-center rounded-3xl border-2 border-dashed p-8 transition-all',
                dragging ? 'border-indigo-400/70 bg-indigo-500/10' : 'border-[var(--line)] bg-white/[0.02] hover:border-white/25')}>
              <input ref={inputRef} type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => handleFile(e.target.files?.[0])} />
              <div className={cn('grid h-20 w-20 place-items-center rounded-2xl transition', busy && 'animate-pulse')} style={{ background: 'linear-gradient(135deg,#6366F1,#22D3EE)' }}>
                {busy ? <Loader2 className="h-8 w-8 animate-spin text-white" /> : ok ? <CheckCircle2 className="h-8 w-8 text-white" /> : <FileUp className="h-8 w-8 text-white" />}
              </div>
              <p className="mt-5 text-sm font-medium text-slate-200">{busy ? stage : '拖入一篇 PDF 论文，或点击选择文件'}</p>
              <p className="mt-2 font-mono text-[11px] text-slate-600">支持 .pdf · 后台走 LIVE 完整抽取</p>
            </div>
          </div>
        )}

        {error && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            className="mx-auto mt-6 flex max-w-2xl items-start gap-3 rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-left">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
            <div>
              <div className="text-sm font-medium text-amber-200">处理失败</div>
              <p className="mt-1 text-[12px] text-slate-300/80">{error}</p>
              <p className="mt-1 text-[12px] text-slate-400/70">请确认 DEMO_MODE=false 并已配置 DashScope/LLM。</p>
            </div>
          </motion.div>
        )}

        <div className="mx-auto mt-8 flex max-w-2xl items-center justify-center gap-2 font-mono text-[11px] text-slate-600">
          <Sparkles className="h-3.5 w-3.5" /> Evidence-first：每条断言都会绑定到论文里的证据。
        </div>
      </section>
    </main>
  );
}
