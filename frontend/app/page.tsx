'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { ArrowUpRight, ArrowRight, BookOpen, FileText, Sparkles, Workflow, UploadCloud } from 'lucide-react';
import { api } from '@/lib/api';
import type { DemoPaperListItem } from '@/lib/types';
import { Logo } from '@/components/Logo';
import { Badge, GlassCard, Kicker, Spinner } from '@/components/ui';

const PIPELINE = [
  { n: '01', label: '多模态解析', sub: '正文 · 图表 · 公式' },
  { n: '02', label: '结构抽取', sub: '章节 · 方法' },
  { n: '03', label: '断言提取', sub: '可验证 Claim' },
  { n: '04', label: '证据链接', sub: '页码 · 区域 · Gate' },
  { n: '05', label: '交互展项', sub: '图谱 · 讲解 · 问答' },
];

export default function Home() {
  const [papers, setPapers] = useState<DemoPaperListItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .demoList()
      .then(setPapers)
      .catch((e) => console.error('demoList', e))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="grid-bg relative min-h-screen overflow-hidden">
      {/* ambient glows */}
      <div className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[900px] -translate-x-1/2 rounded-full bg-indigo-600/20 blur-[140px]" />

      <header className="relative z-10 mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <Logo />
        <div className="flex items-center gap-2 font-mono text-[11px] text-slate-500">
          <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
          {loading ? '正在连接…' : '科研引擎在线'}
        </div>
      </header>

      <section className="relative z-10 mx-auto max-w-6xl px-6 pt-14 pb-6 text-center">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <div className="mx-auto mb-6 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-4 py-1.5 font-mono text-[11px] uppercase tracking-[0.2em] text-slate-400">
            <Sparkles className="h-3.5 w-3.5 text-indigo-300" />
            证据驱动的科研展项
          </div>
          <h1 className="mx-auto max-w-3xl text-5xl font-semibold leading-[1.05] tracking-tight text-white sm:text-6xl">
            放入一篇论文，
            <br />
            <span className="text-gradient">看它变成科学。</span>
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-slate-400">
            ResearchLens 把一篇论文自动转换成{' '}
            <span className="text-slate-200">可验证 · 可演示 · 可交互</span> 的科研成果——
            结构、方法、证据链、研究图谱与讲解，全部受论文原文约束。
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Link
              href="/upload"
              className="inline-flex items-center gap-2 rounded-2xl bg-indigo-500 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-indigo-500/30 transition hover:bg-indigo-400"
            >
              <UploadCloud className="h-4 w-4" />
              放入你的论文（上传 PDF）
              <ArrowRight className="h-4 w-4" />
            </Link>
            <span className="font-mono text-[11px] text-slate-600">或从下方示例论文开始</span>
          </div>
        </motion.div>

        {/* Demo papers */}
        <motion.div
          className="mx-auto mt-12 grid max-w-4xl grid-cols-1 gap-4 text-left sm:grid-cols-3"
          initial="hidden"
          animate="show"
          variants={{ show: { transition: { staggerChildren: 0.12 } } }}
        >
          {loading ? (
            <div className="col-span-3 flex justify-center py-16">
              <Spinner />
            </div>
          ) : (
            papers.map((p) => (
              <motion.div
                key={p.slug}
                variants={{ hidden: { opacity: 0, y: 20 }, show: { opacity: 1, y: 0 } }}
              >
                <Link href={`/paper/${p.slug}`} className="group block h-full">
                  <GlassCard
                    className="flex h-full flex-col p-5 transition-all duration-300 group-hover:-translate-y-1 group-hover:border-white/20"
                    style={{ boxShadow: `0 24px 60px -30px ${p.accent}55` }}
                  >
                    <div className="mb-4 flex items-center justify-between">
                      <span
                        className="grid h-9 w-9 place-items-center rounded-xl"
                        style={{ background: `${p.accent}22`, border: `1px solid ${p.accent}44` }}
                      >
                        <FileText className="h-4.5 w-4.5" style={{ color: p.accent }} />
                      </span>
                      <Badge tone="slate">{p.domain}</Badge>
                    </div>
                    <h3 className="text-sm font-semibold leading-snug text-white">{p.title}</h3>
                    <p className="mt-2 font-mono text-[11px] text-slate-500">{p.subtitle}</p>
                    <div className="mt-auto flex items-center justify-between pt-4">
                      <span className="font-mono text-[11px] text-slate-500">{p.year}</span>
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-indigo-300">
                        打开
                        <ArrowUpRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                      </span>
                    </div>
                  </GlassCard>
                </Link>
              </motion.div>
            ))
          )}
        </motion.div>

        {/* Pipeline strip */}
        <div className="mx-auto mt-16 max-w-4xl">
          <Kicker className="mb-4 text-center">生成式 AI 只负责结构化内容 · 视觉由程序渲染</Kicker>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {PIPELINE.map((step, i) => (
              <motion.div
                key={step.n}
                initial={{ opacity: 0, y: 12 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.06 }}
                className="glass rounded-xl p-3 text-left"
              >
                <div className="font-mono text-[10px] text-indigo-300">{step.n}</div>
                <div className="mt-1 text-xs font-semibold text-slate-200">{step.label}</div>
                <div className="mt-0.5 text-[11px] text-slate-500">{step.sub}</div>
              </motion.div>
            ))}
          </div>
        </div>

        {/* How it reads */}
        <div className="mx-auto mt-16 text-center">
          <Kicker className="mb-4">RESEARCHLENS 能为你做什么</Kicker>
          <div className="mx-auto grid max-w-4xl grid-cols-1 gap-4 text-left sm:grid-cols-3">
            {[
              { icon: FileText, t: '多模态论文理解', d: '正文、图表、公式、图片统一解析；结构→断言→证据。' },
              { icon: BookOpen, t: '可解释的证据链', d: '每条断言绑定页码、区域与原文引用；无证据不进事实层。' },
              { icon: Workflow, t: '交互式科研展项', d: '研究图谱、算法动画、讲解员与 grounded 问答。' },
            ].map((f) => (
              <GlassCard key={f.t} className="p-5">
                <f.icon className="mb-3 h-5 w-5 text-slate-300" />
                <div className="text-sm font-semibold text-white">{f.t}</div>
                <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">{f.d}</p>
              </GlassCard>
            ))}
          </div>
        </div>

        <footer className="mx-auto mt-16 flex max-w-4xl flex-col items-center justify-center gap-3 border-t border-[var(--line)] py-8 font-mono text-[11px] text-slate-600 sm:flex-row sm:gap-6">
          <span>第二届「庆园杯」· 主题三 开放创新探索</span>
          <span className="flex items-center gap-1.5">
            <Sparkles className="h-3 w-3" />
            演示模式 · 无需 API Key 即可体验
          </span>
        </footer>
      </section>
    </main>
  );
}
