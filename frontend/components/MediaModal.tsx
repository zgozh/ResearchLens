'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { X, Table2, Image as ImageIcon, Quote, FileText } from 'lucide-react';
import type { FigureOut, TableOut } from '@/lib/types';
import { Kicker } from '@/components/ui';
import { FigureImage } from '@/components/FigureImage';

export type MediaItem =
  | { type: 'figure'; figure: FigureOut }
  | { type: 'table'; table: TableOut };

export function MediaModal({ item, onClose, accent }: { item: MediaItem | null; onClose: () => void; accent: string }) {
  return (
    <AnimatePresence>
      {item && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur"
          onClick={onClose}
        >
          <motion.div
            initial={{ scale: 0.94, y: 10 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.94, y: 10 }}
            className="max-h-[88vh] w-full max-w-4xl overflow-y-auto rounded-3xl border border-[var(--line)] bg-[#0c1526] p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center gap-2">
              {item.type === 'figure' ? <ImageIcon className="h-4 w-4" style={{ color: accent }} /> : <Table2 className="h-4 w-4" style={{ color: accent }} />}
              <span className="text-sm font-semibold text-white">{item.type === 'figure' ? `图 ${item.figure.fig_no}` : `表 ${item.table.table_no}`}</span>
              <span className="ml-auto font-mono text-[11px] text-slate-500">原图 · p.{item.type === 'figure' ? item.figure.page : item.table.page}</span>
              <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-lg text-slate-400 hover:bg-white/5 hover:text-white">
                <X className="h-4 w-4" />
              </button>
            </div>

            {item.type === 'figure' ? (
              <>
                <div className="overflow-hidden rounded-2xl border border-[var(--line)] bg-[#0F172A] p-3">
                  <FigureImage image_b64={item.figure.image_b64} glyph_svg={item.figure.glyph_svg} caption={item.figure.caption} className="mx-auto max-w-3xl" />
                </div>
                <p className="mt-4 text-[13px] leading-relaxed text-slate-300">{item.figure.caption}</p>
                {item.figure.description && (
                  <p className="mt-2 flex items-start gap-2 text-[12px] text-slate-500">
                    <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {item.figure.description}
                  </p>
                )}
              </>
            ) : (
              <>
                <p className="mb-3 text-[13px] text-slate-400">{item.table.caption}</p>
                <div className="overflow-hidden rounded-2xl border border-[var(--line)]">
                  <table className="w-full text-left text-[14px]">
                    <thead>
                      <tr className="bg-white/[0.04]">
                        {(item.table.content[0] || []).map((h, i) => <th key={i} className="px-3 py-2.5 font-medium text-slate-200">{h}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {item.table.content.slice(1).map((row, ri) => (
                        <tr key={ri} className="border-t border-[var(--line)] hover:bg-white/[0.03]">
                          {row.map((cell, ci) => <td key={ci} className="px-3 py-2.5 text-slate-300">{cell}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {item.table.key_finding && (
                  <div className="mt-3 flex items-start gap-2 rounded-xl border-l-2 border-emerald-400 bg-emerald-500/5 px-3 py-2.5 text-[13px] text-emerald-100/90">
                    <Quote className="mt-0.5 h-4 w-4 shrink-0" /> 关键结论：{item.table.key_finding}
                  </div>
                )}
              </>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
