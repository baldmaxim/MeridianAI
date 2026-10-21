import React from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { openUrl } from "@tauri-apps/plugin-opener";

const isWebUrl = (href: string | undefined): href is string =>
  !!href && /^https?:\/\//i.test(href);

/** Headings, lists and the rest are styled with the theme tokens. */
const COMPONENTS: Components = {
  h1: ({ children }) => (
    <h1 className="mb-2 mt-4 text-lg font-bold text-text first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-2 mt-4 text-base font-bold text-text first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-1.5 mt-3 text-sm font-semibold text-text first:mt-0">
      {children}
    </h3>
  ),
  h4: ({ children }) => (
    <h4 className="mb-1 mt-3 text-sm font-semibold text-muted first:mt-0">
      {children}
    </h4>
  ),
  p: ({ children }) => (
    <p className="mb-2 break-words text-sm leading-relaxed text-text">
      {children}
    </p>
  ),
  ul: ({ children }) => (
    <ul className="mb-2 list-disc space-y-1 ps-5 text-sm text-text marker:text-logo-primary">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal space-y-1 ps-5 text-sm text-text marker:text-muted">
      {children}
    </ol>
  ),
  li: ({ children }) => (
    <li className="break-words leading-relaxed">{children}</li>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-text">{children}</strong>
  ),
  blockquote: ({ children }) => (
    <blockquote className="mb-2 border-s-2 border-logo-primary/60 ps-3 text-muted">
      {children}
    </blockquote>
  ),
  code: ({ children }) => (
    <code className="rounded bg-elevated px-1 py-0.5 font-mono text-xs text-text">
      {children}
    </code>
  ),
  table: ({ children }) => (
    <div className="mb-2 overflow-x-auto">
      <table className="w-full border-collapse text-sm text-text">
        {children}
      </table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-border bg-elevated px-2 py-1 text-start font-semibold">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border border-border px-2 py-1 align-top">{children}</td>
  ),
  hr: () => <hr className="my-3 border-border" />,
  a: ({ href, children }) => (
    <a
      href={href}
      onClick={(event) => {
        // A link must never navigate the app window itself.
        event.preventDefault();
        if (isWebUrl(href)) void openUrl(href).catch(() => undefined);
      }}
      className="cursor-pointer text-logo-primary underline-offset-2 hover:underline"
    >
      {children}
    </a>
  ),
};

interface MarkdownBodyProps {
  markdown: string;
  className?: string;
}

/** Markdown from the server (protocol, assistant answers), safely rendered. */
export const MarkdownBody: React.FC<MarkdownBodyProps> = ({
  markdown,
  className = "",
}) => (
  <div className={`select-text ${className}`}>
    <Markdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
      {markdown}
    </Markdown>
  </div>
);
