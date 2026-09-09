export function collectPricingRows() {

    if (location.href !== "https://bigmodel.cn/pricing") throw new Error("unexpected pricing origin");
    const headers = ["模型名称", "上下文(千tokens)", "输入单价(百万tokens)", "输出单价(百万tokens)", "缓存存储(百万tokens/小时)", "缓存命中(百万tokens)", "输入模态"];
    const rows = [];
    for (const table of document.querySelectorAll(".el-table")) {
      const actual = [...table.querySelectorAll(".el-table__header-wrapper th")].map((cell) => cell.textContent.trim());
      if (JSON.stringify(actual) !== JSON.stringify(headers)) continue;
      for (const row of table.querySelectorAll(".el-table__body-wrapper tbody tr")) {
        const cells = [...row.querySelectorAll(":scope > td")];
        if (cells.length !== headers.length || cells.some((cell) => cell.rowSpan !== 1 || cell.colSpan !== 1)) continue;
        const model = cells[0].querySelector(".name-box p")?.textContent.trim().toLowerCase();
        if (!model || !/^glm-[a-z0-9]+(?:[.-][a-z0-9]+)*$/.test(model)) continue;
        const prices = [2, 3, 4, 5].map((index) => cells[index].textContent.trim());
        if (prices.some((price) => !price || price.length > 500)) throw new Error("invalid pricing row");
        rows.push({ model_id: model, free_claim: prices.every((price) => price === "免费") });
      }
    }
    return rows;
}
