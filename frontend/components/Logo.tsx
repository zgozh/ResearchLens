import { cn } from '@/lib/cn';

export function Logo({ className, size = 34 }: { className?: string; size?: number }) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <div
        className="relative grid place-items-center rounded-xl"
        style={{ width: size, height: size, background: 'linear-gradient(135deg,#6366F1,#22D3EE)' }}
      >
        <svg viewBox="0 0 24 24" width={size * 0.58} height={size * 0.58} fill="none">
          <path
            d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H12l-4 3.2V16H5.5A1.5 1.5 0 0 1 4 14.5v-9Z"
            fill="rgba(255,255,255,0.95)"
          />
          <circle cx="12" cy="10" r="2.4" fill="#0B1220" />
        </svg>
      </div>
      <div className="leading-none">
        <div className="text-[15px] font-bold tracking-tight text-white">ResearchLens</div>
        <div className="mt-0.5 font-mono text-[9px] uppercase tracking-[0.28em] text-slate-400">
          AI 科研视界
        </div>
      </div>
    </div>
  );
}
