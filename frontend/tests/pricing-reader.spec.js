import { expect, test } from "@playwright/test";
import { collectPricingRows } from "../../tools/zhipu-pricing-dom.mjs";

const headers = ["模型名称", "上下文(千tokens)", "输入单价(百万tokens)", "输出单价(百万tokens)", "缓存存储(百万tokens/小时)", "缓存命中(百万tokens)", "输入模态"];
const table = (rows, names = headers) => `<div class="el-table"><div class="el-table__header-wrapper"><table><tr>${names.map((name) => `<th>${name}</th>`).join("")}</tr></table></div><div class="el-table__body-wrapper"><table><tbody>${rows.map(([model, ...prices]) => `<tr><td><div class="name-box"><p>${model}</p></div></td><td>200K</td>${prices.map((price) => `<td>${price}</td>`).join("")}<td>文本</td></tr>`).join("")}</tbody></table></div></div>`;

test("公开价格 DOM 精确区分 Flash、FlashX 与缓存费用，不继承邻行免费", async ({ page }) => {
  await page.route("https://bigmodel.cn/pricing", (route) => route.fulfill({ contentType: "text/html; charset=utf-8", body: table([
    ["GLM-4.7-Flash", "免费", "免费", "免费", "免费"],
    ["GLM-4.7-FlashX", "0.8", "免费", "免费", "免费"],
    ["GLM-4.6V-Flash", "免费", "免费", "0.1", "免费"],
    ["GLM-5", "未知", "免费", "免费", "免费"],
  ]) }));
  await page.goto("https://bigmodel.cn/pricing");
  expect(await page.evaluate(collectPricingRows)).toEqual([
    { model_id: "glm-4.7-flash", free_claim: true },
    { model_id: "glm-4.7-flashx", free_claim: false },
    { model_id: "glm-4.6v-flash", free_claim: false },
    { model_id: "glm-5", free_claim: false },
  ]);
});

test("公开价格 DOM 在列变更或非官方页面时拒绝证据", async ({ page }) => {
  await page.route("https://bigmodel.cn/pricing", (route) => route.fulfill({ contentType: "text/html; charset=utf-8", body: table([
    ["GLM-4.7-Flash", "免费", "免费", "免费", "免费"],
  ], ["模型名称", "任意文本"]) }));
  await page.goto("https://bigmodel.cn/pricing");
  expect(await page.evaluate(collectPricingRows)).toEqual([]);
  await page.goto("about:blank");
  await expect(page.evaluate(collectPricingRows)).rejects.toThrow("unexpected pricing origin");
});
