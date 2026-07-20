import { expect, test } from "@playwright/test";

test("switching inference routes clears a drafted prompt", async ({ page }) => {
  await page.route(/\/vinfer(?:-a|-c)?\/v1\/models$/, (route) =>
    route.fulfill({
      json: {
        data: [{
          id: "8b-q4",
          quant: "Q4_K_M",
          runtime: "llamacpp",
          legs: ["A", "B", "C"],
          status: "available",
          price_per_1m_in_usdc: 1,
          price_per_1m_out_usdc: 1,
        }],
      },
    }),
  );
  await page.route(/\/vinfer(?:-a|-c)?\/v1\/attestation$/, (route) =>
    route.fulfill({
      json: { grade: "none", binding_version: 2 },
    }),
  );
  await page.route(/\/vinfer(?:-a|-c)?\/v1\/auth\/session$/, (route) =>
    route.fulfill({
      json: { required: false, authenticated: true, mode: "open" },
    }),
  );

  await page.goto("/");
  await page
    .getByRole("button", { name: "Open-source models without TEE" })
    .click();
  await expect(page.locator('[data-model="8b-q4"]')).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByLabel("Prompt").fill("private draft for the local route");

  await page
    .getByRole("button", { name: "Claude through TEE proxy" })
    .click();

  await expect(page.getByLabel("Prompt")).toHaveValue("");
});
