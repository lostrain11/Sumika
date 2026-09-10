import Schema from "@deepseek-ai/schemastery";

export const name = "sumika-community-documents";
export const inject = ["tools", "fs"];
export const Config = Schema.object({
  word: Schema.boolean().default(false),
  excel: Schema.boolean().default(false),
  powerpoint: Schema.boolean().default(false),
  pdfRead: Schema.boolean().default(false),
  fileAccessGranted: Schema.boolean().default(false).description("Host user permission for document file access; enabling a feature alone grants no permission.")
});

export const groups = Object.freeze({
  word: ["word_create", "word_read", "word_update"],
  excel: ["excel_create", "excel_read", "excel_update"],
  powerpoint: ["ppt_create", "ppt_read"],
  pdfRead: ["pdf_read"]
});

export async function apply(ctx, config = {}) {
  const resolved = Config(config);
  if (!resolved.fileAccessGranted) return;
  const allowed = new Set(Object.entries(groups).filter(([key]) => resolved[key]).flatMap(([, names]) => names));
  if (!allowed.size) return;
  const facade = {
    fs: ctx.fs,
    effect: ctx.effect.bind(ctx),
    tools: { register: definition => allowed.has(definition.name) ? ctx.tools.register(definition) : () => {} }
  };
  if (resolved.word || resolved.excel || resolved.powerpoint) {
    const office = await import("dsh-office-tools");
    office.apply(facade, { enablePptTools: resolved.powerpoint });
  }
  if (resolved.pdfRead) {
    const pdf = await import("dsh-pdf");
    pdf.apply(facade, { maxFileBytes: 20971520, maxPages: 500, maxCharsPerCall: 12000 });
  }
}
