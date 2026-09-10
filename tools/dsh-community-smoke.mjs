import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

export const name = "sumika-community-smoke";
export const inject = ["tools", "fs"];

export async function apply(ctx, config) {
  if (!path.isAbsolute(config.directory)) throw new Error("Explicit isolated artifact directory required");
    await new Promise(resolve => setTimeout(resolve, 250));
    const receipt = { host: "real-dsh", model: "none", session: "fixture", mode: config.mode, results: [] };
    try {
      await mkdir(config.directory, { recursive: true });
      const groups = { word: ["word_create", "word_read", "word_update"], excel: ["excel_create", "excel_read", "excel_update"], powerpoint: ["ppt_create", "ppt_read"], pdfRead: ["pdf_read"] };
      const actual = ctx.tools.schemas().map(tool => tool.name).filter(tool => Object.values(groups).flat().includes(tool)).sort();
      const expected = config.mode === "all" ? Object.values(groups).flat().sort() : (groups[config.mode] || []).sort();
      assert.deepEqual(actual, expected);
      receipt.registered = actual;
      const controller = new AbortController();
      if (!actual.length) {
        const denied = await ctx.tools.execute({ callId: "disabled-probe", name: "word_read", arguments: { path: "note.docx" }, signal: controller.signal });
        assert.match(JSON.stringify(denied), /UNKNOWN_TOOL/);
        receipt.disabled_dispatch = "UNKNOWN_TOOL";
      }
      const exec = { signal: controller.signal, agent: { session: { header: { cwd: config.directory } } } };
      const call = async (tool, args) => {
        const result = await ctx.tools.get(tool).execute(args, exec);
        receipt.results.push({ tool, result });
        return result;
      };
      if (actual.includes("word_create")) {
        await call("word_create", { path: "note.docx", paragraphs: ["Sumika 中文 document"], overwrite: true });
        assert.match(JSON.stringify(await call("word_read", { path: "note.docx" })), /Sumika/);
        await call("word_update", { path: "note.docx", paragraphs: ["Updated 中文"] });
        assert.match(JSON.stringify(await call("word_read", { path: "note.docx" })), /Updated/);
      }
      if (actual.includes("excel_create")) {
        await call("excel_create", { path: "table.xlsx", sheets: [{ name: "Sheet", rows: [["项目", "金额"], ["Sumika", 42]] }], overwrite: true });
        assert.match(JSON.stringify(await call("excel_read", { path: "table.xlsx" })), /42/);
        await call("excel_update", { path: "table.xlsx", cell_updates: [{ sheet: "Sheet", cell: "B2", value: 43 }] });
        assert.match(JSON.stringify(await call("excel_read", { path: "table.xlsx" })), /43/);
      }
      if (actual.includes("ppt_create")) {
        await call("ppt_create", { path: "slides.pptx", slides: [{ title: "Sumika", paragraphs: ["Basic slide"] }], overwrite: true });
        assert.match(JSON.stringify(await call("ppt_read", { path: "slides.pptx" })), /Sumika/);
      }
      if (actual.includes("pdf_read")) {
        const stream = "BT /F1 12 Tf 50 700 Td (Sumika PDF smoke) Tj ET";
        const objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`];
        let pdf = "%PDF-1.4\n";
        const offsets = [0];
        objects.forEach((object, index) => { offsets.push(Buffer.byteLength(pdf)); pdf += `${index + 1} 0 obj\n${object}\nendobj\n`; });
        const xref = Buffer.byteLength(pdf);
        pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => String(offset).padStart(10, "0") + " 00000 n \n").join("")}trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n${xref}\n%%EOF\n`;
        const file = path.join(config.directory, "source.pdf");
        await writeFile(file, pdf);
        assert.match(await call("pdf_read", { path: file }), /Sumika PDF smoke/);
      }
      if (config.mode === "disabled-after-use") {
        for (const file of ["note.docx", "table.xlsx", "slides.pptx", "source.pdf"]) assert.ok((await readFile(path.join(config.directory, file))).length);
      }
      receipt.status = "passed";
    } catch (error) {
      receipt.status = "failed";
      receipt.error = String(error.stack || error);
    }
    await writeFile(path.join(config.directory, `${config.mode}.json`), JSON.stringify(receipt, null, 2));
    process.stdout.write(`community-smoke: ${receipt.status} (${config.mode})\n`);
    setTimeout(() => process.emit("SIGINT"), 100);
}
