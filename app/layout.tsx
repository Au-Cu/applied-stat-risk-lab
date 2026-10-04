import type { Metadata } from "next";
import "./globals.css";

const repositoryName = process.env.GITHUB_REPOSITORY?.split("/")[1];
const assetBasePath =
  process.env.GITHUB_ACTIONS === "true" && repositoryName
    ? `/${repositoryName}`
    : "";

export const metadata: Metadata = {
  title: "应用统计择校风险实验室",
  description: "基于逐年滚动回测、事件情景与保守上界的应用统计硕士择校风险工具。",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: `${assetBasePath}/favicon.svg`,
    shortcut: `${assetBasePath}/favicon.svg`,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
