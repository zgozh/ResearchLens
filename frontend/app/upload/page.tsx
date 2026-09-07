'use client';

import { useCallback, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { ArrowLeft, FileUp, Loader2, CheckCircle2, AlertTriangle, Sparkles } from 'lucide-react';
import { api } from '@/lib/api';
import { Logo } from '@/components/Logo';
import { Btn, GlassCard, Kicker } from '@/components/ui';
import { cn } from '@/lib/cn';

export default function UploadPage() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<string>('正在上传…');
  const [error, setError] = useState<string>();
  const [ok, setOk] = useState(false);

  const handleFile = useCallback(
    async (file?: File | null) => {
      if (!file) return;
      setBusy(true);
      setOk(false);
      setError(undefined);
      setStage('正在上传论文…');
      try {
        const up = await api.uploadPaper(file);
        setStage('正在调用大模型抽取结构与断言…');
        const proc = await api.processPaper(up.paper_id).catch(() => ({ status: 'skipped' }));
        setOk(true);
        setStage('抽取完成，正在进入科研展项…');
        setTimeout(() => {
          router.push(`/paper/upload?paper_id=${up.paper_id}`);
        }, 700);
      } catch (e: any) {
        setError(e?.message || '上传失败');
        setStage('');
      } finally {
        setBusy(false);
      }
    },
    [router],
  );

  return (
    <main className="grid-bg relative min-h-screen">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-6">
        <div className="flex items-center gap-4">
          <Link href="/" className="flex items-center gap-2 text-slate-400 transition hover:text-white">
            <ArrowLeft className="h-4 w-4" /> 返回
          </Link>
          <Logo />
        </div>
        <Link href="/" className="text-sm font-medium text-indigo-300 hover:text-indigo-200">选示例论文 →</Link>
      </header>

      <section className="mx-auto max-w-3xl px-6 py-10 text-center">
        <Kicker>DROP A PAPER · 放入论文</Kicker>
        <h1 className="mt-3 text-3xl font-semibold text-white">把一篇论文变成可交互的科研成果</h1>
        <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-slate-400">
          上传 PDF 后，ResearchLens 将经过{" "}
          <span className="text-slate-200">多模态解析 → 结构化 → 断言提取 → 证据链接 → 交互展项</span>。
          需要 <span className="text-indigo-300">DEMO_MODE=false 且已配置 DashScope/LLM</span> 才能触发真实抽取。
        </p>

        {/* dropzone */}
        <div className="mt-8">
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files?.[0]); }}
            onClick={() => inputRef.current?.click()}
            className={cn(
              'group relative mx-auto flex min-h-[280px] max-w-2xl cursor-pointer flex-col items-center justify-center rounded-3xl border-2 border-dashed p-8 transition-all',
              dragging ? 'border-indigo-400/70 bg-indigo-500/10' : 'border-[var(--line)] bg-white/[0.02] hover:border-white/25',
            )}
          >
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={(e) => handleFile(e.target.files?.[0])}
            />
            <div className={cn('grid h-20 w-20 place-items-center rounded-2xl transition', busy && 'animate-pulse')}
              style={{ background: 'linear-gradient(135deg,#6366F1,#22D3EE)' }}>
              {busy ? (
                <Loader2 className="h-8 w-8 animate-spin text-white" />
              ) : ok ? (
                <CheckCircle2 className="h-8 w-8 text-white" />
              ) : (
                <FileUp className="h-8 w-8 text-white" />
              )}
            </div>
            <p className="mt-5 text-sm font-medium text-slate-200">
              {busy ? stage : '拖入一篇 PDF 论文，或点击选择文件'}
            </p>
            <p className="mt-2 font-mono text-[11px] text-slate-600">支持 .pdf · 上传后自动走 LIVE 抽取</p>
          </div>
        </div>

        {error && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            className="mx-auto mt-6 flex max-w-2xl items-start gap-3 rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-left">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
            <div>
              <div className="text-sm font-medium text-amber-200">无法上传（可能处于演示模式）</div>
              <p className="mt-1 text-[12px] text-amber-100/80">{error}</p>
              <p className="mt-1 text-[12px] text-slate-300/70">
                请将后端 <code className="rounded bg-black/30 px-1">DEMO_MODE=false</code> 并配置{' '}
                <code className="rounded bg-black/30 px-1">LLM_API_KEY / LLM_BASE_URL / LLM_MODEL</code>，再试。
              </p>
            </div>
          </motion.div>
        )}

        <div className="mx-auto mt-8 flex max-w-2xl items-center justify-center gap-2 font-mono text-[11px] text-slate-600">
          <Sparkles className="h-3.5 w-3.5" />
          Evidence-first：每条断言都会绑定到你论文里的证据。
        </div>
      </section>
    </main>
  );
}
