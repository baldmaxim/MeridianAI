import changelogMd from "../../CHANGELOG.md?raw";

export interface IRelease {
  version: string;
  date: string;
  items: string[];
}

const HEADING_RE = /^##\s+(\d+\.\d+\.\d+)\s+—\s+(\S+)\s*$/;
const BULLET_RE = /^[-*]\s+(.*)$/;

/** Разбирает CHANGELOG.md: секции `## X.Y.Z — ДД.ММ.ГГГГ` и пункты `- ...`. Порядок как в файле. */
export const parseChangelog = (md: string): IRelease[] => {
  const releases: IRelease[] = [];
  let inComment = false;
  let current: IRelease | null = null;
  for (const raw of md.split(/\r?\n/)) {
    const line = raw.trim();
    if (inComment) {
      if (line.includes("-->")) inComment = false;
      continue;
    }
    if (line.startsWith("<!--")) {
      if (!line.includes("-->")) inComment = true;
      continue;
    }
    const heading = HEADING_RE.exec(line);
    if (heading) {
      current = { version: heading[1], date: heading[2], items: [] };
      releases.push(current);
      continue;
    }
    if (line.startsWith("#")) {
      current = null;
      continue;
    }
    const bullet = BULLET_RE.exec(line);
    if (current && bullet && bullet[1]) current.items.push(bullet[1]);
  }
  return releases;
};

/** Пункты версии из текста CHANGELOG; пусто, если секции нет. */
export const releaseNotes = (md: string, version: string): string[] =>
  parseChangelog(md).find((r) => r.version === version)?.items ?? [];

/** Пункты из `update.body`: строки с `- `; без маркеров — непустые строки. */
export const parseNotesBody = (body: string): string[] => {
  const lines = body
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  const bullets = lines.flatMap((l) => {
    const m = BULLET_RE.exec(l);
    return m && m[1] ? [m[1]] : [];
  });
  return bullets.length > 0 ? bullets : lines;
};

/** Встроенные в приложение релизы (новые сверху). */
export const BUNDLED_RELEASES: IRelease[] = parseChangelog(changelogMd);

/** Пункты версии из встроенного CHANGELOG. */
export const bundledReleaseNotes = (version: string): string[] =>
  releaseNotes(changelogMd, version);
