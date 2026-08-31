export const sourceColumns = [
  { key: "codex_tokens", label: "Codex", fidelity: "exact" },
  { key: "gemini_openclaw_tokens", label: "Gemini / Open Claw", fidelity: "exact" },
  { key: "gemini_export_est", label: "Gemini export", fidelity: "estimated" },
  { key: "chatgpt_est", label: "ChatGPT", fidelity: "estimated" },
] as const;

export type SourceKey = (typeof sourceColumns)[number]["key"];

export type RawBurnRow = {
  date: string;
  codex_tokens?: number;
  gemini_openclaw_tokens?: number;
  gemini_export_est?: number;
  chatgpt_est?: number;
  total?: number;
  driver: string;
  evidence?: string;
};

export type BurnRow = Required<Pick<RawBurnRow, SourceKey>> &
  Omit<RawBurnRow, SourceKey | "total"> & {
    total: number;
  };

export function normalizeRows(rows: RawBurnRow[]): BurnRow[] {
  return rows
    .map((row) => {
      const codex = asNumber(row.codex_tokens);
      const geminiOpenClaw = asNumber(row.gemini_openclaw_tokens);
      const geminiExport = asNumber(row.gemini_export_est);
      const chatgpt = asNumber(row.chatgpt_est);
      const computedTotal = codex + geminiOpenClaw + geminiExport + chatgpt;

      return {
        date: row.date,
        codex_tokens: codex,
        gemini_openclaw_tokens: geminiOpenClaw,
        gemini_export_est: geminiExport,
        chatgpt_est: chatgpt,
        total: asNumber(row.total) || computedTotal,
        driver: row.driver || "unlabeled",
        evidence: row.evidence || "",
      };
    })
    .sort((a, b) => a.date.localeCompare(b.date));
}

export function sumSource(rows: BurnRow[], key: SourceKey) {
  return rows.reduce((sum, row) => sum + row[key], 0);
}

function asNumber(value: number | undefined) {
  return Number.isFinite(value) ? Number(value) : 0;
}
