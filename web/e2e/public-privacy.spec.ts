import { expect, test } from "@playwright/test";

const accessCode = process.env.VINFER_TEST_ACCESS_CODE;

test("TEE console sends and receives chat text only as ciphertext", async ({ page }) => {
  test.skip(!accessCode, "VINFER_TEST_ACCESS_CODE is required for the live test");
  const marker = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const prompt = `Reply with exactly SEALED_OUTPUT_${marker}`;
  let requestBody = "";

  page.on("request", (request) => {
    if (request.url().includes("/vinfer/v1/chat_e2e")) {
      requestBody = request.postData() ?? "";
    }
  });

  await page.goto("/");
  await page.getByLabel("test access").fill(accessCode!);
  await page.getByRole("button", { name: "sign in" }).click();
  await expect(page.getByText("test session active")).toBeVisible();
  await expect(page.getByText("trusted · browser sealing on")).toBeVisible({
    timeout: 60_000,
  });

  const responsePromise = page.waitForResponse(
    (response) => response.url().includes("/vinfer/v1/chat_e2e"),
  );
  await page.getByLabel("Prompt").fill(prompt);
  await page.getByLabel("Max tokens").fill("32");
  await page.getByRole("button", { name: "run" }).click();
  const response = await responsePromise;

  expect(response.ok()).toBe(true);
  expect(response.headers()["content-type"]).toContain("text/event-stream");
  expect(requestBody).not.toContain(prompt);
  const request = JSON.parse(requestBody) as Record<string, unknown>;
  expect(Object.keys(request).sort()).toEqual([
    "ciphertext",
    "enc",
    "max_tokens",
    "model",
    "stream",
  ]);
  expect(request.stream).toBe(true);
  expect(typeof request.enc).toBe("string");
  expect(typeof request.ciphertext).toBe("string");

  const assistant = page.locator(".msg.assistant:not(.error) .msg-body").last();
  await expect(assistant).not.toHaveText("");
  const assistantText = (await assistant.textContent())?.trim() ?? "";
  expect(assistantText.length).toBeGreaterThan(0);
  await expect(page.getByText("end-to-end sealed", { exact: true })).toBeVisible();
  await expect(page.getByText("confirmed", { exact: true })).toBeVisible();
  await expect(page.locator(".msg.error")).toHaveCount(0);
});
