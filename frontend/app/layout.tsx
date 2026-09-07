import type { Metadata } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter', display: 'swap' });
const jet = JetBrains_Mono({ subsets: ['latin'], variable: '--font-jetbrains', display: 'swap' });

export const metadata: Metadata = {
  title: 'ResearchLens · AI 科研视界',
  description:
    '让一篇论文从「文档」变成「可验证、可演示、可交互的科研成果」—— 证据驱动的多模态科研展项。',
  icons: { icon: '/favicon.svg' },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" className={`${inter.variable} ${jet.variable}`}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
