import { expect, test } from "@playwright/test";

test("switching inference routes clears a drafted prompt", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Prompt").fill("private draft for the TEE route");

  await page
    .getByRole("button", { name: "Open-source models without TEE" })
    .click();

  await expect(page.getByLabel("Prompt")).toHaveValue("");
});
