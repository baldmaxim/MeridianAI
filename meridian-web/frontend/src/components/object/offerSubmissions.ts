import type { DocumentRecord } from '../../types';

const SEP = ' · ';
// «КП <номер> · <дата или "файл YYYY-MM-DD"> · » — дальше идёт папка подачи (если есть) и имя файла.
const PREFIX_RE = /^КП [^·]+ · (?:файл )?\d{4}-\d{2}-\d{2} · /;
const PREFIX_WITH_FOLDER_RE = /^КП [^·]+ · \d{4}-\d{2}-\d{2} · /;

/** Срезает с имени файла подачи префикс «КП N · дата · [папка · ]». Не совпало по формату — имя как есть. */
export const stripOfferPrefix = (name: string, submission: string): string => {
  const re = submission ? PREFIX_WITH_FOLDER_RE : PREFIX_RE;
  const m = re.exec(name);
  if (!m) return name;
  let rest = name.slice(m[0].length);
  if (submission) {
    if (!rest.startsWith(submission + SEP)) return name;
    rest = rest.slice(submission.length + SEP.length);
  }
  return rest || name;
};

interface IWithSubmission {
  offer_submission?: string | null;
}

export interface IObjectDocumentsSplit<T extends IWithSubmission = DocumentRecord> {
  bySubmission: Map<string, T[]>;
  general: T[];
}

/** offer_submission == null → общий контекст; строка (в т.ч. "") → подача КП с этим ключом. */
export const splitObjectDocuments = <T extends IWithSubmission>(docs: readonly T[]): IObjectDocumentsSplit<T> => {
  const bySubmission = new Map<string, T[]>();
  const general: T[] = [];
  docs.forEach((d) => {
    if (d.offer_submission == null) {
      general.push(d);
      return;
    }
    const list = bySubmission.get(d.offer_submission);
    if (list) list.push(d); else bySubmission.set(d.offer_submission, [d]);
  });
  return { bySubmission, general };
};
